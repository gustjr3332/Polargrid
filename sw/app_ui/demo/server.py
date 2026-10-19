#!/usr/bin/env python3
"""Demo page server (viewer role: reads the CSE only, never writes).

Run inside WSL, where the CSEs are:
    python3 server.py --live --mns 10               # reads MN 1..10 (ports 3001..3010), serves http://0.0.0.0:8000
    python3 server.py --live --mns 10 --record replay/day.jsonl
    python3 server.py --replay replay/day.jsonl     # plays a recording, no CSE needed
    python3 server.py --bench 7 --mns 10            # time N full reads of all cells and exit

Endpoints: /api/frame (latest frame, ?fresh=1 reads now), /api/events (SSE frames), /api/topology,
/api/flow (SSE, events for the flow viewer), /flow (flow viewer), / (demo page).
Plan: docs/PolaGrid_시연페이지_계획.md section 7 for the frame format.
"""
import argparse
import asyncio
import collections
import hmac
import json
import os
import re
import sqlite3
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
RUNS = HERE / "runs.json"
CORR_DB = HERE / "corrections.db"
DDL = """CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, run TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('too_bright', 'too_dark')),
  amount_lux REAL NOT NULL,   -- slider size, always positive
  offset_lux REAL NOT NULL,   -- wanted change of the desk light: -amount (too bright) or +amount (too dark), as in polagrid/prefs.py
  level INTEGER, desk_lux REAL, cell_lux REAL,   -- cell open level and light readings when the button was pressed (NULL if unreadable)
  fake INTEGER NOT NULL)      -- 1 = the cell was tools/fake_cell.py, so not a real preference"""


def corr_db():
    db = sqlite3.connect(CORR_DB)
    db.row_factory = sqlite3.Row
    db.execute(DDL)
    return db
OPS = {1: "CREATE", 2: "RETRIEVE", 3: "UPDATE", 4: "DELETE", 5: "NOTIFY"}
_tl = threading.local()


def http_get(url, orig):
    """GET as viewer. Returns (status, json or None, seconds)."""
    s = getattr(_tl, "s", None) or requests.Session()
    _tl.s = s
    t0 = time.perf_counter()
    try:
        r = s.get(url, headers={"X-M2M-Origin": orig, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3",
                                "Accept": "application/json"}, timeout=10)
        try:
            body = r.json()
        except ValueError:
            body = None
        return r.status_code, body, time.perf_counter() - t0
    except requests.RequestException:
        return 0, None, time.perf_counter() - t0


class Hub:
    """Live data from the CSEs, the latest frame, and the event stream for the flow viewer."""

    def __init__(self, n_mn, workers, interval, record=None):
        self.mns = [{"k": k, "host": f"http://127.0.0.1:{3000 + k}", "cse": f"TinyIoT-mn{k:03d}", "run": None,
                     "cells": [], "orig": None, "levels": [], "lt": {}, "seen": {}} for k in range(1, n_mn + 1)]
        self.pool = ThreadPoolExecutor(workers)
        self.interval, self.record = interval, record
        self.frame, self.frame_id = None, 0
        self.events = collections.deque(maxlen=3000)   # (id, event dict)
        self.eid = 0
        self.stats = {"gets": 0, "get_err": 0, "cin_seen": 0, "state_changes": 0, "mqtt_msgs": 0, "mqtt_err": 0,
                      "started": time.time(), "last_read_ms": None}
        self.lock = threading.Lock()
        self.moves = 0

    # ---- events ----
    def emit(self, **ev):
        with self.lock:
            self.eid += 1
            ev["id"], ev["ts"] = self.eid, time.time()
            self.events.append(ev)

    def get(self, mn, path, orig=None):
        st, body, dt = http_get(f"{mn['host']}/{mn['cse']}/{path}", orig or mn["orig"])
        with self.lock:
            self.stats["gets"] += 1
            if st not in (200, 404):
                self.stats["get_err"] += 1
        return st, body, dt

    # ---- discovery ----
    def discover(self):
        """Find each zone's cells by label-less type discovery (fu=1&ty=28) as that zone's viewer originator.
        The run id of each MN comes from runs.json ({"1": "r34365", ...}): an unknown originator on a 100-cell MN
        crashed tinyIoT (stack smashing, 2026-10-16), so we never probe with a made-up originator."""
        runs = json.loads(RUNS.read_text()) if RUNS.exists() else {}
        for mn in self.mns:
            run = runs.get(str(mn["k"]))
            mn.update(run=None, cells=[])
            if not run:
                continue
            st, body, _ = http_get(f"{mn['host']}/{mn['cse']}?fu=1&ty=28&lbl=polagrid/{run}/state", f"C{run}view")
            if st != 200:
                continue
            idx = {}
            for p in body.get("m2m:uril", []):
                m = re.search(rf"/{run}p(\d+)/state$", p)
                if m:
                    idx[int(m[1])] = p
            mn["run"], mn["orig"] = run, f"C{run}view"
            mn["cells"] = [idx[i] for i in sorted(idx)]
            mn["levels"], mn["lt"] = [None] * len(mn["cells"]), {}
        return [(m["cse"], m["run"], len(m["cells"])) for m in self.mns]

    # ---- one full read ----
    def read_frame(self):
        t0 = time.perf_counter()
        jobs = []
        for mn in self.mns:
            for i, p in enumerate(mn["cells"]):
                jobs.append((mn, i, self.pool.submit(self._cell, mn, p)))
        env = [(mn, self.pool.submit(self._env, mn)) for mn in self.mns if mn["run"]]
        changed = collections.defaultdict(list)
        for mn, i, f in jobs:
            lvl, lt = f.result()
            if lvl is not None:
                if mn["lt"].get(i) not in (None, lt):
                    changed[mn["k"]].append(i)
                mn["levels"][i], mn["lt"][i] = lvl, lt
        suns, lux = [], []
        for mn, f in env:
            sun, desks = f.result()
            if sun:
                suns.append(sun)
            lux += desks
        read_ms = (time.perf_counter() - t0) * 1000
        for k, cells in changed.items():
            mn = self.mns[k - 1]
            self.moves += len(cells)
            self.stats["state_changes"] += len(cells)
            self.emit(kind="state", mn=k, src=f"cell AE C{mn['run']}p*", path=f"{mn['cse']}/{mn['run']}p*/state",
                      op="UPDATE", rsc=2004, n=len(cells), cells=cells[:200], note="state changed (seen by lt)")
        sun = suns[0] if suns else {}
        cells = [v if v is not None else 0 for mn in self.mns for v in mn["levels"]]
        f = {"t": (sun.get("t") or "")[:16], "cells": cells,
             "desks": [round(sum(lux) / len(lux)), round(min(lux))] if lux else [0, 0],
             "sun": {"elev": sun.get("alt"), "lux": sun.get("outdoor")},
             "glare_h": None, "lat_ms": None, "moves": self.moves,   # glare and command latency are not visible to a viewer
             "read_ms": round(read_ms), "n_cells": len(cells)}
        self.stats["last_read_ms"] = f["read_ms"]
        return f

    def _cell(self, mn, path):
        st, body, _ = self.get(mn, path.split("/", 1)[1])
        if st != 200:
            return None, None
        d = body["cod:opeLl"]
        return d.get("opeLl"), d.get("lt")

    def _env(self, mn):
        sun = desks = None
        run = mn["run"]
        st, b, _ = self.get(mn, f"{run}env/sun/la")
        if st == 200:
            sun = json.loads(b["m2m:cin"]["con"])
        st, b, _ = self.get(mn, f"{run}env/desks/la")
        lux = json.loads(b["m2m:cin"]["con"]).get("lux", []) if st == 200 else []
        return sun, lux

    # ---- loops ----
    def frame_loop(self):
        seen = None
        while True:
            t0 = time.time()
            mt = RUNS.stat().st_mtime if RUNS.exists() else None
            if mt != seen or not any(m["cells"] for m in self.mns):   # runs.json rewritten: new zones, look again
                seen = mt
                self.discover()
            try:
                f = self.read_frame()
            except Exception as e:                      # keep serving the last frame
                self.emit(kind="error", src="server", path="", op="READ", rsc=0, note=repr(e))
                f = None
            if f:
                self.frame_id += 1
                self.frame = f
                if self.record:
                    with open(self.record, "a") as fh:
                        fh.write(json.dumps(f) + "\n")
            time.sleep(max(0.0, self.interval - (time.time() - t0)))

    def cin_loop(self):
        """Poll the newest CIN of each zone's sun, desks and cell 0 command (a member of the command group): a new `ri` is one CIN."""
        while True:
            t0 = time.time()
            for mn in self.mns:
                run = mn["run"]
                if not run:
                    continue
                for name, path, src in (("sun", f"{run}env/sun", "env sensor"), ("desks", f"{run}env/desks", "env sensor"),
                                        ("command", f"{run}p0/command", "GRP fan-out of controller command")):
                    st, b, _ = self.get(mn, path + "/la")
                    if st != 200:
                        continue
                    cin = b["m2m:cin"]
                    if mn["seen"].get(name) == cin["ri"]:
                        continue
                    first = name not in mn["seen"]
                    mn["seen"][name] = cin["ri"]
                    if first:
                        continue                        # only report CINs that appear while we watch
                    try:
                        con = json.loads(cin["con"])
                    except ValueError:
                        con = {}
                    with self.lock:
                        self.stats["cin_seen"] += 1
                    note = (f"{len(con.get('lux', []))} desks" if name == "desks" else
                            f"{len(con.get('angles', []))} angles" if name == "command" else
                            f"outdoor {con.get('outdoor')} lux, sun alt {con.get('alt')}")
                    self.emit(kind="cin", mn=mn["k"], name=name, src=src, path=f"{mn['cse']}/{path}", op="CREATE CIN",
                              rsc=2001, cmd=con.get("cmd"), note=note)
                if mn["cells"]:                         # cell 0's state, polled every second so step 3 of a command gets a sharper time
                    st, b, _ = self.get(mn, mn["cells"][0].split("/", 1)[1])
                    lt = b["cod:opeLl"].get("lt") if st == 200 else None
                    if lt and mn["seen"].get("state0") not in (None, lt):
                        self.emit(kind="p0state", mn=mn["k"], src=f"cell AE C{run}p0", path=f"{mn['cse']}/{run}p0/state",
                                  op="UPDATE", rsc=2004, note=f"opeLl {b['cod:opeLl'].get('opeLl')}")
                    if lt:
                        mn["seen"]["state0"] = lt
            time.sleep(max(0.0, 1.0 - (time.time() - t0)))

    def mqtt_loop(self):
        while True:
            try:
                p = subprocess.Popen(["mosquitto_sub", "-t", "#", "-v"], stdout=subprocess.PIPE, text=True, errors="replace")
                for line in p.stdout:
                    topic, _, payload = line.partition(" ")
                    try:
                        m = json.loads(payload)
                    except ValueError:
                        m = {}
                    with self.lock:
                        self.stats["mqtt_msgs"] += 1
                    kind = topic.split("/")[2] if topic.count("/") >= 3 else "?"
                    ids = re.findall(r"id-mn(\d+)", topic)
                    self.emit(kind="mqtt", mn=int(ids[0]) if ids else None, src=m.get("fr") or topic.split("/")[3:4] and topic.split("/")[3],
                              path=m.get("to") or "", op=OPS.get(m.get("op"), "RESPONSE" if kind == "resp" else "?"),
                              rsc=m.get("rsc", ""), note=topic)
            except FileNotFoundError:
                with self.lock:
                    self.stats["mqtt_err"] += 1
                return
            time.sleep(2)


def con_of(body, key="m2m:cin"):
    """CIN content as a dict. tinyIoT returns a string, or a JSON object after a restart."""
    c = body[key]["con"]
    return json.loads(c) if isinstance(c, str) else c


_disc = {"t": 0.0, "idx": []}   # cell indexes found by label, kept a few seconds so the page's 2 s polling does not discover every time


def read_real(real):
    """The real cells (or fake_cell.py) as the app sees them, viewer GETs only. Cells are found by the state label
    polagrid/<run>/state; each one's place in the window is its label polagrid/<run>/pos/<row>/<col> (row 0 = top, col 0 = left,
    seen from inside; a cell without it goes to row 0, col = its index). level is the mean open level of all cells."""
    base, run, orig = f"{real['host']}/{real['cse']}", real["run"], f"C{real['run']}view"
    out = {"run": run, "ok": False, "level": None, "cell_lux": None, "desk_lux": None, "fake": None, "lt": None, "cells": []}
    if time.time() - _disc["t"] > 3:
        st, b, _ = http_get(f"{base}?fu=1&ty=28&lbl=polagrid/{run}/state", orig)
        found = sorted({int(m[1]) for u in (b or {}).get("m2m:uril", []) if (m := re.search(rf"(?:^|/){run}p(\d+)/state$", u))}) if st == 200 else []
        _disc.update(t=time.time(), idx=found or [0])   # discovery refused: the first cell at least
    for i in _disc["idx"]:
        st, b, _ = http_get(f"{base}/{run}p{i}/state", orig)
        if st != 200:
            continue
        d = b["cod:opeLl"]
        pos = next((re.fullmatch(rf"polagrid/{run}/pos/(\d+)/(\d+)", l) for l in d.get("lbl", []) if re.fullmatch(rf"polagrid/{run}/pos/(\d+)/(\d+)", l)), None)
        out["cells"].append({"i": i, "row": int(pos[1]) if pos else 0, "col": int(pos[2]) if pos else i, "level": d.get("opeLl")})
        if out["lt"] is None:
            out["lt"] = d.get("lt")
    levels = [c["level"] for c in out["cells"] if c["level"] is not None]
    if not levels:
        return out
    out.update(ok=True, level=round(sum(levels) / len(levels)))
    first = out["cells"][0]["i"]
    for key, path in (("cell_lux", f"p{first}/lux/la"), ("desk_lux", "env/desks/la")):
        st, b, _ = http_get(f"{base}/{run}{path}", orig)
        if st == 200:
            d = con_of(b)
            v = d.get("lux")
            out[key] = v[0] if isinstance(v, list) else v
            out["fake"] = bool(out["fake"] or d.get("fake"))
    return out


def build_app(hub, replay, real=None, token=None):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()

    @app.middleware("http")
    async def need_token(request, call_next):
        """With a token set, every POST (move cells, save a correction, start/stop the zones) must carry it in X-Demo-Token.
        Reads stay open. The page takes it from ?token=... of its address."""
        if token and request.method == "POST" and not hmac.compare_digest(request.headers.get("x-demo-token", ""), token):
            return JSONResponse({"error": "token required"}, 401)
        return await call_next(request)
    state = {"frame": None, "id": 0}

    def latest():
        return (hub.frame, hub.frame_id) if hub else (state["frame"], state["id"])

    async def replay_loop():
        frames = [json.loads(l) for l in Path(replay["file"]).read_text().splitlines() if l.strip()]
        state["frame"], state["id"] = frames[0], 1
        await state["go"].wait()        # start the day when the first page connects, not when the server starts
        while True:
            for f in frames:
                state["frame"], state["id"] = f, state["id"] + 1
                await asyncio.sleep(replay["interval"] / state.get("speed", 1.0))   # 1x = interval s per frame, 2x half, 5x a fifth
            if not replay["loop"]:
                return

    @app.on_event("startup")
    async def _start():
        if not hub:
            state["go"] = asyncio.Event()
            asyncio.create_task(replay_loop())

    @app.get("/api/frame")
    def frame(fresh: int = 0):
        if hub and fresh:
            f = hub.read_frame()
            return {**f, "mode": "live"}
        f, _ = latest()
        return JSONResponse({**f, "mode": "live" if hub else "replay"} if f else {"error": "no frame yet"}, 200 if f else 503)

    @app.get("/api/events")
    async def events():
        if not hub:
            state["go"].set()
        async def gen():
            last = -1
            while True:
                f, i = latest()
                if f and i != last:
                    last = i
                    yield f"data: {json.dumps({**f, 'mode': 'live' if hub else 'replay'})}\n\n"
                await asyncio.sleep(0.25)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/ctl")
    def ctl(body: dict):
        """Forward a page control (running, speed, cloud, turn, reset) to every zone started with --serve."""
        if not hub:    # a recording only has a speed
            if "speed" in body and float(body["speed"]) in (1.0, 2.0, 5.0):
                state["speed"] = float(body["speed"])
                return {"speed": state["speed"]}
            return JSONResponse({"error": "replay mode has only the speed control (1, 2, 5)"}, 409)
        ok = 0
        for m in hub.mns:
            try:
                requests.post(f"http://127.0.0.1:{9502 + 10 * m['k']}/ctl", json=body, timeout=2).raise_for_status()
                ok += 1
            except requests.RequestException:
                pass
        return {"zones_ok": ok, "zones": len(hub.mns)}

    @app.get("/api/topology")
    def topology():
        if not hub:
            return {"mode": "replay", "mns": []}
        return {"mode": "live", "mns": [{"k": m["k"], "cse": m["cse"], "run": m["run"], "n_cells": len(m["cells"]),
                                         "levels": m["levels"]} for m in hub.mns], "stats": hub.stats,
                "server_time": time.time()}

    @app.get("/api/flow")
    async def flow():
        async def gen():
            last = hub.eid if hub else 0
            tick = 0
            while True:
                if hub:
                    with hub.lock:
                        new = [e for e in hub.events if e["id"] > last]
                    for e in new:
                        last = e["id"]
                        yield f"data: {json.dumps(e)}\n\n"
                    tick += 1
                    if tick % 4 == 0:
                        yield f"event: stats\ndata: {json.dumps({**hub.stats, 'now': time.time()})}\n\n"
                else:
                    yield "event: stats\ndata: {\"replay\": true}\n\n"
                await asyncio.sleep(0.25)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/real")
    def real_cell():
        """Level and light of the one real cell for the phone mockup (/mockup/?live=1). Read-only."""
        if not real:
            return JSONResponse({"error": "start the server with --real RUN"}, 404)
        return read_real(real)

    @app.post("/api/real/level")
    def real_level(body: dict):
        """A cell touched in the phone mockup (or all cells): open level 0..100 -> tools/real_cell.py app, which sends the command to the CSE."""
        if not real:
            return JSONResponse({"error": "start the server with --real RUN"}, 404)
        try:
            level = float(body["level"])
            idx = None if body.get("i") is None else int(body["i"])
            picked = None if body.get("cells") is None else [int(k) for k in body["cells"]]
            if not 0 <= level <= 100 or (idx is not None and idx < 0) or (picked is not None and min(picked, default=0) < 0):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "need {level: 0..100, i: cell index or cells: [indexes], none = every cell}"}, 400)
        try:
            r = requests.post(f"http://127.0.0.1:{real['app_port']}/level", json={"level": level, "i": idx, "cells": picked}, timeout=5)
            r.raise_for_status()
        except requests.RequestException:
            return JSONResponse({"error": "real_cell.py app is not running"}, 503)
        return r.json()

    @app.post("/api/real/correction")
    def add_correction(body: dict):
        """'Too bright' / 'Too dark' from the Comfort screen: one row in corrections.db with the cell state at that moment."""
        if not real:
            return JSONResponse({"error": "start the server with --real RUN"}, 404)
        try:
            kind, amount = body["kind"], float(body["amount"])
            if kind not in ("too_bright", "too_dark") or not 50 <= amount <= 1000:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "need {kind: too_bright|too_dark, amount: 50..1000}"}, 400)
        r = read_real(real)
        ts = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
        with corr_db() as db:
            db.execute("INSERT INTO corrections (ts, run, kind, amount_lux, offset_lux, level, desk_lux, cell_lux, fake) "
                       "VALUES (?,?,?,?,?,?,?,?,?)",
                       (ts, real["run"], kind, amount, -amount if kind == "too_bright" else amount,
                        r["level"], r["desk_lux"], r["cell_lux"], int(bool(r["fake"]))))
        return {"saved": True, "ts": ts}

    @app.get("/api/real/corrections")
    def corrections():
        with corr_db() as db:
            n = db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
            last = [dict(x) for x in db.execute("SELECT * FROM corrections ORDER BY id DESC LIMIT 5")]
        return {"count": n, "last": last}

    @app.get("/compare.json")
    def compare():
        return FileResponse(HERE / "compare.json")   # built by make_compare.py from the measured baseline CSV

    @app.get("/flow")
    def flow_page():
        return FileResponse(HERE / "static" / "flow.html")

    @app.get("/")
    def index():
        return FileResponse(HERE / "static" / "index.html")

    app.mount("/mockup", StaticFiles(directory=HERE.parent / "mockup", html=True), name="mockup")
    return app


def bench(hub, n, label):
    print(f"# {label}: {sum(len(m['cells']) for m in hub.mns)} cells on {len([m for m in hub.mns if m['cells']])} MN(s), "
          f"workers={hub.pool._max_workers}, {n} full reads (cells + sun/desks per zone)")
    ts = []
    for i in range(n):
        f = hub.read_frame()
        ts.append(f["read_ms"])
        print(f"read {i + 1}: {f['read_ms']} ms, {f['n_cells']} cells, get errors so far {hub.stats['get_err']}")
        time.sleep(0.5)
    s = sorted(ts)
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    print(f"# {label}: n={n} p50={statistics.median(ts):.0f} ms p95={p95} ms max={s[-1]} ms min={s[0]} ms")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--live", action="store_true")
    g.add_argument("--replay", metavar="FILE")
    g.add_argument("--bench", type=int, metavar="N")
    ap.add_argument("--mns", type=int, default=10)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between frames")
    ap.add_argument("--record", metavar="FILE")
    ap.add_argument("--loop", action="store_true", help="replay: start over at the end")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--real", metavar="RUN", help="run id of the one real cell, served at /api/real (phone mockup /mockup/?live=1)")
    ap.add_argument("--token", default=os.environ.get("DEMO_TOKEN"), help="require this token (X-Demo-Token) on every POST; env DEMO_TOKEN. Without it anyone on the network can move the cells")
    ap.add_argument("--real-host", default="http://127.0.0.1:3001")
    ap.add_argument("--real-cse", default="TinyIoT-mn001")
    ap.add_argument("--real-app-port", type=int, default=9600, help="port of tools/real_cell.py app")
    a = ap.parse_args()
    if not a.token:
        print("NOTE: no --token: anyone who can reach this port can move the cells and write corrections")
    real = {"run": a.real, "host": a.real_host, "cse": a.real_cse, "app_port": a.real_app_port} if a.real else None

    if a.replay:
        import uvicorn
        app = build_app(None, {"file": a.replay, "interval": a.interval, "loop": a.loop}, real, a.token)
        return uvicorn.run(app, host="0.0.0.0", port=a.port)
    hub = Hub(a.mns, a.workers, a.interval, a.record)
    if a.record:
        Path(a.record).parent.mkdir(parents=True, exist_ok=True)
    print("discovered:", hub.discover())
    if a.bench:
        return bench(hub, a.bench, f"{a.mns} MN")
    for fn in (hub.frame_loop, hub.cin_loop, hub.mqtt_loop):
        threading.Thread(target=fn, daemon=True).start()
    import uvicorn
    uvicorn.run(build_app(hub, None, real, a.token), host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
