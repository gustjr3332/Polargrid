"""PC side of the ONE real cell (ESP32 firmware in sw/actuator): drives it through the MN-CSE it polls.

The firmware makes the zone.py resources for one cell ({run}env/sun, {run}env/desks, {run}p0/command, state, lux),
so this script runs the normal polagrid Controller as the zone controller of a one-cell zone. --run, --host and --cse
match RUN_ID, CSE_HOST and CSE_NAME in sw/actuator/src/secrets.h (--host as this PC sees the MN). Setup is safe to
repeat with the same run id. Run inside WSL next to the MN, because the CSE calls back into this process on --port.

    python3 tools/real_cell.py --run real1 manual          # type angles 0..90, see state, lux and latency
    python3 tools/real_cell.py --run real1 manual 45 90 0  # the same with angles from the command line
    python3 tools/real_cell.py --run real1 sweep --n 5     # angle vs lux, 0,10,..,90,0 -> results/real_cell_sweep_*.csv
    python3 tools/real_cell.py --run real1 ai --speed 120  # AI (1)+(2) with a SIMULATED sun clock

Every mode resends the last angle at least every HEARTBEAT_MIN (wall time) so the cell's 30 min watchdog never opens
it while this runs, and sends OPEN (angle 0) on exit or Ctrl+C. CSE errors are retried with backoff 1, 2, 4 .. 60 s.
Without hardware run tools/fake_cell.py with the same --run first; its readings are marked fake and so is the CSV.
"""
import argparse
import csv
import math
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid import online                                        # noqa: E402
from polagrid.closed_loop import HEARTBEAT_MIN                     # noqa: E402
from polagrid.onem2m import Client, _headers, con as cin_con   # noqa: E402
from polagrid.physics import KST, Room, sun_position, window_lux   # noqa: E402
from polagrid.zone import Controller, roles                        # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"
SWEEP = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 0]
CSE_ERRORS = (requests.RequestException, RuntimeError, OSError, ValueError, KeyError, TypeError)   # odd replies too
# One 150 mm cell and one desk sensor in front of it (the demo table). Geometry is a guess, only the AI prior uses it.
ROOM = Room(rows=1, cols=1, cell_w=0.15, cell_h=0.15, desks=[(0.0, 0.6, 0.4, 0.3, 0.75)])


def backoff_s(fails):
    """Wait after n failures in a row: 1, 2, 4 ... 60 s (the firmware's m2m::backoffMs)."""
    return 0 if fails <= 0 else min(60, 2 ** min(fails - 1, 6))


def retry(fn, what, tries=None, sleep=time.sleep):
    """fn() until it stops raising a CSE error. tries=None retries forever; otherwise None after `tries` failures."""
    fails = 0
    while True:
        try:
            return fn()
        except CSE_ERRORS as e:
            fails += 1
            if tries is not None and fails >= tries:
                print(f"[retry] {what} failed {fails}x, giving up: {e}")
                return None
            print(f"[retry] {what}: {str(e)[:120]}; again in {backoff_s(fails)} s")
            sleep(backoff_s(fails))


def malus_fit(angles, lux):
    """Fit lux = a cos^2(angle - offset) + b (offset searched over -15..15 deg). Returns a, b, offset, rms residual."""
    th, y = np.radians(np.asarray(angles, float)), np.asarray(lux, float)
    best = None
    for off in np.arange(-15, 15.05, 0.1):
        x = np.column_stack([np.cos(th - math.radians(off)) ** 2, np.ones_like(th)])
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        rms = float(np.sqrt(np.mean((x @ coef - y) ** 2)))
        if best is None or rms < best[3]:
            best = (float(coef[0]), float(coef[1]), round(float(off), 1), rms)
    return best


def sweep_rows(points):
    """[(angle, [lux readings])] -> [(angle, mean lux, ratio to the first point)]. The first point is angle 0."""
    means = [float(np.mean(v)) for _, v in points]
    return [(a, round(m, 1), round(m / means[0], 4) if means[0] else float("nan")) for (a, _), m in zip(points, means)]


def new_readings(get_la, n, timeout_s=120, poll_s=1.0, clock=time.monotonic, sleep=time.sleep):
    """n readings newer than the one there now. get_la() -> (ri, lux, fake) of the newest CIN, or None.
    Returns ([lux], any fake); fewer than n if timeout_s passes."""
    first = get_la()
    seen, out, fake = {first[0]} if first else set(), [], False
    end = clock() + timeout_s
    while len(out) < n and clock() < end:
        sleep(poll_s)
        r = get_la()
        if r and r[0] not in seen:
            seen.add(r[0])
            out.append(r[1])
            fake |= r[2]
    return out, fake


class Cell:
    """The controller side of the one-cell zone, with heartbeat and safe exit."""

    def __init__(self, client, run, port):
        self.c, self.run, self.me = client, run, roles(run)["ctl"]
        self.ctl = Controller(client, run, port)
        self.ctl.seq = int(time.time())   # command ids must differ from an earlier run's: the cell skips a repeated id
        self.angle, self.sent = 0.0, time.monotonic()
        self.lock, self.stop = threading.Lock(), threading.Event()

    def setup(self):
        print(f"[setup] waiting for cell {self.run}p0 on {self.c.host}/{self.c.cse} ...")
        retry(lambda: self.ctl.setup(1, exist_ok=True), "controller setup")
        print("[setup] controller ready (group of 1 cell, desk subscription)")
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def send(self, angle, tries=None):
        """Command one angle; (seconds until the cell's desk reply, desk lux) or None if the cell did not answer."""
        angle = min(90.0, max(0.0, float(angle)))

        def once():
            try:
                t0 = time.perf_counter()
                r = self.ctl.command([angle])
                return time.perf_counter() - t0, float(r["desk_lux"][0])
            except TimeoutError:
                return None                           # the CIN is posted; the cell did not report back in 30 s
        with self.lock:
            got = retry(once, f"command {angle}", tries)
            self.angle, self.sent = angle, time.monotonic()
        return got

    def _heartbeat(self):
        while not self.stop.wait(10):
            if time.monotonic() - self.sent >= HEARTBEAT_MIN * 60:
                print(f"[heartbeat] resend {self.angle:.0f} deg")
                self.send(self.angle)

    def la(self, path):
        """(ri, con) of the newest CIN or the resource at path, as the controller."""
        r = self.c._session().get(f"{self.c.host}/{self.c.cse}/{path}", headers=_headers(self.me), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"GET {path}: {r.status_code} {r.text[:120]}")
        return r.json()

    def state(self):
        return self.la(f"{self.run}p0/state")["cod:opeLl"]["opeLl"]

    def lux(self, sensor):
        """Newest reading (ri, lux, fake) of the cell sensor ({run}p0/lux) or the desk sensor ({run}env/desks)."""
        path = f"{self.run}p0/lux/la" if sensor == "cell" else f"{self.run}env/desks/la"
        cin = self.la(path)["m2m:cin"]
        con = cin_con(cin)
        return cin["ri"], float(con["lux"] if sensor == "cell" else con["lux"][0]), bool(con.get("fake"))

    def close(self):
        """OPEN on exit. Bounded retries; if they all fail the cell's own watchdog opens it within 30 min."""
        self.stop.set()
        print("[exit] sending OPEN (0 deg)")
        got = self.send(0, tries=5)
        print("[exit] cell open" if got else "[exit] no reply from the cell; its watchdog opens it within 30 min")


def show(cell, angle, got):
    if got is None:
        print(f"  {angle:.0f} deg: no desk reply within 30 s (cell offline, or the disc did not arrive)")
        return
    want = round(100 * math.cos(math.radians(angle)) ** 2)
    level = None
    for _ in range(5):                             # the cell PUTs state at most once a second, it can lag the reply
        level = retry(cell.state, "read state", 3)
        if level == want:
            break
        time.sleep(1)
    cl = retry(lambda: cell.lux("cell"), "read cell lux", 3)
    print(f"  {angle:.0f} deg: applied in {got[0]:.1f} s, state opeLl={level} (expect {want}), "
          f"desk {got[1]:.1f} lux, cell sensor (newest, up to 10 s old) {cl[1] if cl else '?'} lux{'  [FAKE CELL]' if cl and cl[2] else ''}")


def manual(cell, a):
    for v in a.angles:
        show(cell, v, cell.send(v))
    if a.angles:
        return
    print("angle 0..90 (0 = open), empty line or q to quit")
    while (line := input("> ").strip()) not in ("", "q"):
        try:
            v = float(line)
        except ValueError:
            print("  not a number")
            continue
        if not 0 <= v <= 90:
            print("  0..90 only")
            continue
        show(cell, v, cell.send(v))


def sweep(cell, a):
    points, fake = [], False
    for ang in SWEEP:
        got = cell.send(ang)
        if got is None:
            print(f"  {ang} deg: cell did not settle (no desk reply), stopping the sweep")
            break
        vals, f = new_readings(lambda: retry(lambda: cell.lux(a.sensor), "read lux", 3), a.n,
                               timeout_s=a.n * 15 + 30)
        fake |= f
        if not vals:
            print(f"  {ang} deg: no new {a.sensor} readings, stopping the sweep")
            break
        points.append((ang, vals))
        print(f"  {ang:>2} deg: settled in {got[0]:.1f} s, {len(vals)} readings, mean {np.mean(vals):.1f} lux")
    if len(points) < 3:
        print("[sweep] too few points, no CSV")
        return
    rows = sweep_rows(points)
    tag = "_FAKE" if fake else ""
    out = RESULTS / f"real_cell_sweep{tag}_{datetime.now():%m%d_%H%M}.csv"
    with open(out, "w", newline="") as f:
        if fake:
            f.write("# FAKE DATA from tools/fake_cell.py (simulated cos^2 model), not a measurement\n")
        f.write(f"# run {cell.run}, sensor {a.sensor}, {a.n} readings per angle, {datetime.now(KST).isoformat()}\n")
        w = csv.writer(f)
        w.writerow(["angle", "lux", "ratio"])
        w.writerows(rows)
    amp, base, off, rms = malus_fit([r[0] for r in rows], [r[1] for r in rows])
    print(f"[sweep] wrote {out}{'  (FAKE data)' if fake else ''}")
    print(f"[malus] lux = {amp:.1f} cos^2(angle {-off:+.1f}) + {base:.1f}, rms residual {rms:.1f} lux "
          f"({100 * rms / max(abs(amp), 1e-9):.1f}% of the swing); repeat 0 deg ratio {rows[-1][2]}")


def ai_loop(cell, a):
    """AI (1) online + AI (2) for one cell. Desk lux is the real sensor; the sun is a SIMULATED accelerated clock."""
    t0 = datetime.fromisoformat(a.start).replace(tzinfo=KST)
    wall0, ctrl = time.monotonic(), online.polagrid_online(ROOM)
    env = roles(cell.run)["env"]
    print(f"[ai] SIMULATED SUN: clock starts {t0:%m-%d %H:%M}, {a.speed:g}x; desk lux from the real sensor")
    while True:
        tick = time.monotonic()
        t = t0 + timedelta(seconds=(tick - wall0) * a.speed)
        alt, az = sun_position(t, ROOM.lat, ROOM.lon)
        sun = {"t": t.isoformat(), "alt": round(alt, 2), "az": round(az, 2), "outdoor": round(window_lux(ROOM, t, a.cloud))}
        retry(lambda: cell.c.create(f"{cell.run}env/sun", env, sun), "publish sun")
        sun = retry(cell.ctl.sun, "read sun")
        desk = retry(cell.ctl.desks, "read desks")
        new = ctrl({"t": t, "outdoor": sun["outdoor"], "angles": np.array([cell.angle]), "desk_lux": desk})
        line = f"[ai] sim {t:%H:%M} sun alt {alt:5.1f} outdoor {sun['outdoor']:>6} lux | desk {desk[0]:7.1f} lux"
        if abs(new[0] - cell.angle) > 0.05:
            got = cell.send(new[0])
            line += f" -> {new[0]:.0f} deg" + (f" in {got[0]:.1f} s" if got else " (no reply)")
        print(line + f" | cell at {cell.angle:.0f} deg")
        time.sleep(max(0.0, a.step - (time.monotonic() - tick)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="http://127.0.0.1:3001", help="MN as this PC sees it (CSE_HOST)")
    ap.add_argument("--cse", default="TinyIoT-mn001", help="CSE_NAME")
    ap.add_argument("--run", default="real1", help="RUN_ID")
    ap.add_argument("--port", type=int, default=9791, help="notification port of this process")
    sub = ap.add_subparsers(dest="mode", required=True)
    m = sub.add_parser("manual")
    m.add_argument("angles", nargs="*", type=float, help="angles to apply in order; none = prompt")
    s = sub.add_parser("sweep")
    s.add_argument("--n", type=int, default=5, help="lux readings averaged per angle (one every 10 s)")
    s.add_argument("--sensor", choices=["cell", "desk"], default="cell")
    i = sub.add_parser("ai")
    i.add_argument("--start", default="2026-11-04T09:00", help="simulated clock start (KST)")
    i.add_argument("--speed", type=float, default=60, help="simulated seconds per wall second")
    i.add_argument("--step", type=float, default=20, help="wall seconds per control step (a 90 deg turn takes ~13 s)")
    i.add_argument("--cloud", type=float, default=0.0, help="simulated cloud 0..1")
    a = ap.parse_args()
    if a.mode == "manual" and any(not 0 <= v <= 90 for v in a.angles):
        ap.error("angles must be 0..90")

    cell = Cell(Client(a.host, a.cse), a.run, a.port)
    try:
        cell.setup()
        {"manual": manual, "sweep": sweep, "ai": ai_loop}[a.mode](cell, a)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        cell.close()


if __name__ == "__main__":
    main()
