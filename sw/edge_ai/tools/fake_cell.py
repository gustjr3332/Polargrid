"""FAKE cell for testing tools/real_cell.py without hardware. Behaves like the ESP32 firmware (sw/actuator) over HTTP.

Same resources, originators and timing as src/main.cpp: provisions {run}env (sun, desks) and {run}p0 (command, state,
lux) as the firmware does (409 = already there), polls {run}p0/command/la every 2 s, turns a pretend disc at the
firmware speed (about 7 deg/s, 90 deg in 12.8 s), PUTs state when opeLl changes, answers each command with a desk CIN
carrying its cmd id, and every 10 s posts a periodic desk reading and the cell sensor. No command for 30 min opens it.
Light is a made-up Malus model, lux = lamp cos^2(disc) + leak, plus 1 % noise. Every reading carries "fake": true.

    python3 tools/fake_cell.py --run real1
    python3 tools/fake_cell.py --run real1 --index 1 --row 0 --col 1   # a second cell, to the right of the first

--row/--col are CELL_ROW/CELL_COL of the firmware: where the cell sits in the window seen from inside (row 0 = top, col 0 =
left). The app draws each cell there. --index is CELL_INDEX (resource {run}p<index>, entry <index> of a command's angle list).
"""
import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from polagrid.onem2m import Client, _headers, con as cin_con   # noqa: E402
from polagrid.zone import ALL, C, DISC, N, OPEN_LEVEL, R, make_acp, remote, roles   # noqa: E402
from real_cell import CSE_ERRORS, backoff_s                         # noqa: E402

DEG_PER_S = 1 / (4096 * 150 / 24 / 360 * 0.002)   # firmware: STEPS_PER_DISC_DEG half steps, one every 2 ms
POLL_S, REPORT_S, WATCHDOG_S = 2, 10, 30 * 60


def provision(c, run, index, row, col):
    o, me, cell = roles(run), f"C{run}p{index}", f"{run}p{index}"
    rules = lambda owner: [([owner], ALL), (remote(o["ctl"]), C | R | N | DISC), (remote(o["view"]), R | N | DISC)]
    env_acp = make_acp(c, f"{run}envacp", rules(o["env"]), exist_ok=True)
    cell_acp = make_acp(c, f"{cell}acp", rules(me), exist_ok=True)
    ae = lambda rn: {"m2m:ae": {"rn": rn, "api": "Npolagrid", "rr": False, "srv": ["3"]}}
    cnt = lambda rn, acp, lbl=None: {"m2m:cnt": {"rn": rn, "mni": 10, "acpi": [acp], **({"lbl": [lbl]} if lbl else {})}}
    for path, orig, body, ty in [
            ("", o["env"], ae(f"{run}env"), 2),
            (f"{run}env", o["env"], cnt("sun", env_acp), 3),
            (f"{run}env", o["env"], cnt("desks", env_acp), 3),
            ("", me, ae(cell), 2),
            (cell, me, cnt("command", cell_acp, f"polagrid/{run}/command"), 3),
            (cell, me, {"cod:opeLl": {"rn": "state", "cnd": OPEN_LEVEL, "opeLl": 100, "minLl": 0, "maxLl": 100,
                                      "acpi": [cell_acp], "lbl": [f"polagrid/{run}/state", f"polagrid/{run}/pos/{row}/{col}"]}}, 28),
            (cell, me, cnt("lux", cell_acp), 3)]:
        c.post(path, orig, body, ty, exist_ok=True)


def main():
    ap = argparse.ArgumentParser(description="FAKE cell (no hardware), firmware behaviour over HTTP")
    ap.add_argument("--host", default="http://127.0.0.1:3001")
    ap.add_argument("--cse", default="TinyIoT-mn001")
    ap.add_argument("--run", default="real1")
    ap.add_argument("--index", type=int, default=0, help="CELL_INDEX")
    ap.add_argument("--row", type=int, default=0, help="CELL_ROW (0 = top)")
    ap.add_argument("--col", type=int, default=None, help="CELL_COL (0 = left), default = --index")
    ap.add_argument("--lamp", type=float, default=800.0, help="fake cell-sensor lux with the disc open")
    ap.add_argument("--leak", type=float, default=15.0, help="fake cell-sensor lux with the disc closed")
    a = ap.parse_args()
    c, run, rng = Client(a.host, a.cse), a.run, np.random.default_rng(a.index)
    idx, col = a.index, a.index if a.col is None else a.col
    me, env, cell_rn = f"C{run}p{idx}", roles(run)["env"], f"{run}p{idx}"
    disc = target = 0.0
    last_cmd = pending = None
    published, ready, fails = None, False, 0
    last_poll = last_report = last_rx = t_prev = time.monotonic()
    privacy = False
    cell_lux = lambda: (a.lamp * math.cos(math.radians(disc)) ** 2 + a.leak) * (1 + 0.01 * rng.standard_normal())
    desk_lux = lambda: 0.5 * cell_lux() + 40
    print(f"[FAKE cell] {cell_rn} at row {a.row} col {col}, run {run} on {a.host}/{a.cse}, {DEG_PER_S:.2f} deg/s")
    while True:
        time.sleep(0.05)
        now = time.monotonic()
        step = DEG_PER_S * (now - t_prev)
        t_prev = now
        disc = target if abs(target - disc) <= step else disc + math.copysign(step, target - disc)
        try:
            if not ready:
                provision(c, run, idx, a.row, col)
                ready, fails, published, last_poll = True, 0, None, 0.0   # poll at once
                print("[FAKE cell] CSE ready")
            if now - last_poll >= POLL_S:
                last_poll = now
                r = c._session().get(f"{c.host}/{c.cse}/{cell_rn}/command/la", headers=_headers(me), timeout=10)
                if r.status_code == 403:
                    ready = False
                elif r.status_code == 404 and last_cmd is None:
                    last_cmd = ""               # no command yet, so the first one that appears is new
                elif r.status_code == 200:
                    con = cin_con(r.json()["m2m:cin"])
                    if last_cmd is None:        # like the firmware: the first command seen after boot is an old one, remember it only
                        last_cmd = con["cmd"]
                        print(f"[FAKE cell] SKIP old command {last_cmd} after boot (the heartbeat sends a fresh one)")
                    elif con["cmd"] != last_cmd:
                        last_cmd, pending, last_rx = con["cmd"], con["cmd"], now
                        privacy = con.get("mode") == "privacy"   # like the firmware: all dark, the watchdog leaves it alone
                        want = float(con["angles"][idx if idx < len(con["angles"]) else 0])
                        target = 90.0 if privacy else want if 0 <= want <= 90 else 0.0   # nonsense angle (or NaN): open
                        print(f"[FAKE cell] {con['cmd']}: {disc:.0f} -> {target:.0f} deg" + (" (privacy)" if privacy else ""))
            if now - last_rx > WATCHDOG_S and target and not privacy:
                target, last_rx = 0.0, now
                print("[FAKE cell] watchdog: no command for 30 min, opening")
            if disc == target:
                level = round(100 * math.cos(math.radians(disc)) ** 2)
                if level != published:
                    c.put(f"{cell_rn}/state", me, {"cod:opeLl": {"opeLl": level}})
                    published = level
                if pending:
                    time.sleep(0.25)
                    c.create(f"{run}env/desks", env, {"cmd": pending, "lux": [round(desk_lux(), 1)], "fake": True})
                    pending = None
            if now - last_report >= REPORT_S:
                last_report = now
                c.create(f"{run}env/desks", env, {"cmd": f"t{int(now)}", "lux": [round(desk_lux(), 1)], "fake": True})
                c.create(f"{cell_rn}/lux", me, {"lux": round(cell_lux(), 1), "fake": True})
        except CSE_ERRORS as e:
            fails += 1
            print(f"[FAKE cell] CSE error: {str(e)[:100]}; again in {backoff_s(fails)} s")
            time.sleep(backoff_s(fails))
            ready = False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
