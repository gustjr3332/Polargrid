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
import json
import re
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).parent
RUNS = HERE / "runs.json"
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


def build_app(hub, replay):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

    app = FastAPI()
    state = {"frame": None, "id": 0}

    def latest():
        return (hub.frame, hub.frame_id) if hub else (state["frame"], state["id"])

    async def replay_loop():
        frames = [json.loads(l) for l in Path(replay["file"]).read_text().splitlines() if l.strip()]
        while True:
            for f in frames:
                state["frame"], state["id"] = f, state["id"] + 1
                await asyncio.sleep(replay["interval"])
            if not replay["loop"]:
                return

    @app.on_event("startup")
    async def _start():
        if not hub:
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
        if not hub:
            return JSONResponse({"error": "replay mode has no controls"}, 409)
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

    @app.get("/flow")
    def flow_page():
        return FileResponse(HERE / "static" / "flow.html")

    @app.get("/")
    def index():
        return FileResponse(HERE / "static" / "index.html")

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
    a = ap.parse_args()

    if a.replay:
        import uvicorn
        app = build_app(None, {"file": a.replay, "interval": a.interval, "loop": a.loop})
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
    uvicorn.run(build_app(hub, None), host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
