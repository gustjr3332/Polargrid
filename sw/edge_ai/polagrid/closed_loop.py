"""Closed loop on tinyIoT: virtual cells + MEC controller exchange everything through an MN-CSE.

Runs one simulated day over oneM2M, then the same day directly on the physics model (polagrid.evaluate), and
prints both plus command latency. Controllers: "probe" = AI (1)+(2), which probes every cell (n+1 commands per
probe), "predict" = AI (3), which commands once per step from a model trained on directly simulated days.

Run inside WSL, where the CSE and its notification callbacks live (IN and mn001 up: tools/run_in.sh, sim/nodes.sh):
    python3 -m polagrid.closed_loop --day 2026-11-05 --step 15
"""
import argparse
import statistics
from datetime import date, datetime, timedelta

import numpy as np

from . import ai, evaluate
from .onem2m import Client
from .physics import DESK_MIN_LUX, KST, Room, simulate, sun_position
from .zone import Controller, Zone, roles


def run_day(zone, ctl, day, controller, cloud, step_min):
    """Same loop and metrics as evaluate.run_day, but sun and desk readings come through the CSE."""
    room = zone.room
    angles = np.zeros(room.n_cells)
    t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
    glare_h = dark_h = lux_sum = 0.0
    steps = 12 * 60 // step_min
    for _ in range(steps):
        zone.set_environment(t, cloud)
        sun = ctl.sun()
        ctx = {"t": t, "outdoor": sun["outdoor"], "angles": angles, "measure": ctl.command,
               "x": ai.features(t, sun["alt"], sun["az"], sun["outdoor"])}
        new = controller(ctx)
        if np.max(np.abs(new - angles)) > 0.05:
            ctl.command(new)
        angles = np.asarray(new, dtype=float)
        truth = simulate(room, t, zone.angles, cloud)
        glare_h += step_min / 60 * np.sum(truth["glare"] > 0)
        if sun_position(t, room.lat, room.lon)[0] > 0:
            dark_h += step_min / 60 * np.sum(truth["desk_lux"] < DESK_MIN_LUX)
        lux_sum += truth["desk_lux"].mean()
        t += timedelta(minutes=step_min)
    return {"glare_h": glare_h, "dark_h": dark_h, "mean_lux": lux_sum / steps, "moves": int(zone.moves)}


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
    ap.add_argument("--cloud", type=float, default=0.0)
    ap.add_argument("--step", type=int, default=5, help="simulated minutes per control step")
    ap.add_argument("--controller", choices=["probe", "predict"], default="probe")
    ap.add_argument("--probe", type=int, default=15, help="simulated minutes between AI (1) probes")
    ap.add_argument("--train-days", type=int, default=60, help="training days for the predict controller")
    ap.add_argument("--port", type=int, default=9500)
    a = ap.parse_args()

    room, day = Room(rows=a.rows, cols=a.cols), date.fromisoformat(a.day)
    run = f"r{int(datetime.now().timestamp()) % 100000}"
    client = Client(a.host, a.cse)
    zone, ctl = Zone(client, room, run, a.port), Controller(client, run, a.port + 1)
    zone.setup()
    ctl.setup(room.n_cells)
    print(f"[setup] {room.n_cells} cells on {a.cse}, run {run}")
    check_acp(client, run, room.n_cells)

    if a.controller == "probe":
        make = lambda: evaluate.polagrid_probe(room.n_cells, a.probe)
    else:
        train = evaluate.days(date(2026, 1, 1), a.train_days, 365 // a.train_days, seed=1)
        logs = [row for d, cloud in train for row in evaluate.teacher_log(room, d, cloud)]
        model = ai.fit_predictor([x for x, _ in logs], [ang for _, ang in logs])
        make = lambda: evaluate.polagrid_predict(model)
        print(f"[train] {len(train)} days, {len(logs)} samples")
    over_cse = run_day(zone, ctl, day, make(), a.cloud, a.step)
    direct, _ = evaluate.run_day(room, day, make(), a.cloud)
    lat = ctl.latencies
    print(f"{'':<22}{'glare h':>9}{'under-lit h':>13}{'mean lux':>10}{'servo moves':>13}")
    for name, m in (("over oneM2M (CSE)", over_cse), ("direct physics", direct)):
        print(f"{name:<22}{m['glare_h']:>9.2f}{m['dark_h']:>13.2f}{m['mean_lux']:>10.0f}{m['moves']:>13.0f}")
    print(f"[latency] {len(lat)} commands to {room.n_cells} cells: command -> desk reading "
          f"p50={statistics.median(lat) * 1000:.0f}ms p95={pct(lat, .95) * 1000:.0f}ms max={max(lat) * 1000:.0f}ms")


if __name__ == "__main__":
    main()
