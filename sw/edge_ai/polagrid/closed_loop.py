"""Closed loop on tinyIoT: virtual cells + MEC controller exchange everything through an MN-CSE.

Runs one simulated day over oneM2M, then the same day directly on the physics model (polagrid.evaluate), and
prints both plus command latency. Controllers: "probe" = AI (1)+(2), which probes every cell (n+1 commands per
probe), "online" = AI (1) estimated from the desk readings the CSE delivers (no probing; --real-turn makes the
physical window differ from the model it starts from), "predict" = AI (3), which commands once per step from a model trained on directly simulated days.

Run inside WSL, where the CSE and its notification callbacks live (IN and mn001 up: tools/run_in.sh, sim/nodes.sh):
    python3 -m polagrid.closed_loop --day 2026-11-05 --step 15
"""
import argparse
import dataclasses
import json
import statistics
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from . import ai, evaluate, online, virtual, weather
from .onem2m import Client
from .physics import DESK_MIN_LUX, KST, Room, simulate, sun_position
from .zone import WATCHDOG_MIN, Controller, Zone, roles

HEARTBEAT_MIN = WATCHDOG_MIN // 3   # resend the table at least this often, or the cells' watchdog opens them


class Control:
    """Demo page controls (POST /ctl on the control port): start/stop, speed, cloud, window turn, reset."""
    STEP_WALL_S = 2.0                    # wall seconds per control step at 1x

    def __init__(self, cloud, azimuth):
        self.running, self.speed, self.cloud, self.turn, self.reset = False, 1.0, cloud, 0.0, False
        self.base_cloud, self.azimuth = cloud, azimuth

    def serve(self, port):
        ctl = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if "running" in body: ctl.running = bool(body["running"])
                if "speed" in body: ctl.speed = max(0.1, float(body["speed"]))
                if "cloud" in body: ctl.cloud = float(body["cloud"]) if body["cloud"] else ctl.base_cloud
                if "turn" in body: ctl.turn = float(body["turn"])
                if body.get("reset"): ctl.reset = True
                self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

            def log_message(self, *a): pass
        threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever, daemon=True).start()


def run_day(zone, ctl, day, controller, cloud, step_min, ctrl=None):
    """Same loop and metrics as evaluate.run_day, but sun and desk readings come through the CSE."""
    room = zone.room
    angles = np.zeros(room.n_cells)
    t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
    glare_h = dark_h = lux_sum = 0.0
    steps = 12 * 60 // step_min
    sent, timeouts = t, 0
    for _ in range(steps):
        if ctrl:
            t0 = time.time()
            while not ctrl.running and not ctrl.reset:
                time.sleep(0.1)
            if ctrl.reset:
                return None
            cloud = ctrl.cloud
            zone.room = dataclasses.replace(zone.room, window_azimuth=ctrl.azimuth + ctrl.turn)   # turned window
            room = zone.room
        zone.set_environment(t, cloud)
        sun = ctl.sun()
        ctx = {"t": t, "outdoor": sun["outdoor"], "angles": angles, "measure": ctl.command, "desk_lux": ctl.desks(),
               "x": ai.features(t, sun["alt"], sun["az"], sun["outdoor"])}
        new = controller(ctx)
        if np.max(np.abs(new - angles)) > 0.05 or t - sent >= timedelta(minutes=HEARTBEAT_MIN):
            try:
                ctl.command(new)
                sent, angles = t, np.asarray(new, dtype=float)
            except TimeoutError:
                timeouts += 1                     # CSE unreachable: keep the old table, the cells' watchdog covers us
        truth = simulate(room, t, zone.angles, cloud)
        glare_h += step_min / 60 * np.sum(truth["glare"] > 0)
        if sun_position(t, room.lat, room.lon)[0] > 0:
            dark_h += step_min / 60 * np.sum(truth["desk_lux"] < DESK_MIN_LUX)
        lux_sum += truth["desk_lux"].mean()
        t += timedelta(minutes=step_min)
        if ctrl:
            time.sleep(max(0.0, Control.STEP_WALL_S / ctrl.speed - (time.time() - t0)))
    return {"glare_h": glare_h, "dark_h": dark_h, "mean_lux": lux_sum / steps, "moves": int(zone.moves),
            "timeouts": timeouts, "watchdog_opens": zone.watchdog_opens}


def check_acp(client, run, n_cells):
    """Each role gets exactly its rights: a cell cannot touch another cell, the viewer cannot write but can
    find every cell's state by label. The CSE also rejects a state that breaks the openLevel schema."""
    view = roles(run)["view"]
    client.post("", view, {"m2m:ae": {"rn": f"{run}view", "api": "Npolagrid", "rr": False, "srv": ["3"]}}, 2)
    level = lambda v: {"cod:opeLl": {"opeLl": v}}
    got = {"cell p1 -> p0/state": client.code("PUT", f"{run}p0/state", f"C{run}p1", level(50)),
           "viewer -> env/desks": client.code("POST", f"{run}env/desks", view, {"m2m:cin": {"con": "{}"}}, 4),
           "viewer reads p0/state": client.code("GET", f"{run}p0/state", view),
           "cell p0 bad openLevel": client.code("PUT", f"{run}p0/state", f"C{run}p0", level("x")),
           "viewer finds states": len(client.discover(view, lbl=f"polagrid/{run}/state", ty=28))}
    want = {"cell p1 -> p0/state": 403, "viewer -> env/desks": 403, "viewer reads p0/state": 200,
            "cell p0 bad openLevel": 400, "viewer finds states": n_cells}
    print("[acp] " + ", ".join(f"{k}={v}" for k, v in got.items()))
    assert got == want, f"access control differs: want {want}"


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:3001")
    ap.add_argument("--cse", default="TinyIoT-mn001")
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--day", default="2026-11-05")
    ap.add_argument("--cloud", type=float, default=0.0, help="constant cloud 0..1 (also the fallback of --sky)")
    ap.add_argument("--sky", choices=["const", "kma", "openmeteo", "forecast"], default="const",
                    help="hourly sky from polagrid.weather: cached 2025 archive (--day in 2025) or live Open-Meteo forecast")
    ap.add_argument("--site", choices=list(weather.SITES), default="seoul", help="room location and weather site")
    ap.add_argument("--step", type=int, default=5, help="simulated minutes per control step")
    ap.add_argument("--controller", choices=["probe", "online", "predict"], default="probe")
    ap.add_argument("--probe", type=int, default=15, help="simulated minutes between AI (1) probes")
    ap.add_argument("--train-days", type=int, default=60, help="training days for the predict controller")
    ap.add_argument("--model", help="saved predictor from `python -m polagrid.virtual train` (predict controller)")
    ap.add_argument("--real-turn", type=float, default=0.0,
                    help="degrees the physical window is turned away from the model room (online controller)")
    ap.add_argument("--port", type=int, default=9500)
    ap.add_argument("--serve", action="store_true",
                    help="demo mode: wait for Start on the control port (port+2) and repeat the day after Reset")
    a = ap.parse_args()

    lat, lon = weather.SITES[a.site]
    room, day = Room(rows=a.rows, cols=a.cols, lat=lat, lon=lon), date.fromisoformat(a.day)
    a.cloud = weather.sky(a.site, day, a.sky, a.cloud)       # constant or hourly real/forecast sky (kt)
    real = dataclasses.replace(room, window_azimuth=room.window_azimuth + a.real_turn)   # what the cells really see
    run = f"r{int(datetime.now().timestamp()) % 100000}"
    client = Client(a.host, a.cse)
    zone, ctl = Zone(client, real, run, a.port), Controller(client, run, a.port + 1)
    zone.setup()
    ctl.setup(room.n_cells)
    print(f"[setup] {room.n_cells} cells on {a.cse}, run {run}")
    check_acp(client, run, room.n_cells)

    if a.controller == "probe":
        make = lambda: evaluate.polagrid_probe(room.n_cells, a.probe)
    elif a.controller == "online":
        make = lambda: online.polagrid_online(room)
    elif a.model:
        model = virtual.load(room, a.model)
        make = lambda: evaluate.polagrid_predict(model)
        print(f"[model] loaded {a.model}")
    else:
        model = virtual.train(room, a.train_days, jitter=False)   # same teacher and margin as a saved model
        make = lambda: evaluate.polagrid_predict(model)
        print(f"[train] {a.train_days} days")
    base = make
    make = lambda: evaluate.night_closed(base())
    if a.serve:
        ctrl = Control(a.cloud, real.window_azimuth)
        ctrl.serve(a.port + 2)
        while True:
            ctrl.reset = ctrl.running = False
            ctrl.turn, ctrl.cloud = 0.0, a.cloud
            zone.set_environment(datetime(day.year, day.month, day.day, 7, tzinfo=KST), a.cloud)   # clock back to 07:00
            if run_day(zone, ctl, day, make(), a.cloud, a.step, ctrl) is not None:
                ctrl.running = False
                while not ctrl.reset:                      # day finished: hold the last frame until Reset
                    time.sleep(0.2)
    over_cse = run_day(zone, ctl, day, make(), a.cloud, a.step)
    direct, _ = evaluate.run_day(real, day, make(), a.cloud)
    print(f"[safety] night mode on; over CSE: {over_cse['timeouts']} command timeouts, "
          f"{over_cse['watchdog_opens']} watchdog opens (cells open after {WATCHDOG_MIN} min without a command)")
    lat = ctl.latencies
    print(f"{'':<22}{'glare h':>9}{'under-lit h':>13}{'mean lux':>10}{'servo moves':>13}")
    for name, m in (("over oneM2M (CSE)", over_cse), ("direct physics", direct)):
        print(f"{name:<22}{m['glare_h']:>9.2f}{m['dark_h']:>13.2f}{m['mean_lux']:>10.0f}{m['moves']:>13.0f}")
    print(f"[latency] {len(lat)} commands to {room.n_cells} cells: command -> desk reading "
          f"p50={statistics.median(lat) * 1000:.0f}ms p95={pct(lat, .95) * 1000:.0f}ms max={max(lat) * 1000:.0f}ms")


if __name__ == "__main__":
    main()
