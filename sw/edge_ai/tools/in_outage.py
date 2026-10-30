"""IN outage test driver: controller + probes against one MN, with the IN stopped from outside (run_in_outage.sh).
Sends an angle every --period s through the MN (real_cell.Cell, as in `real_cell.py ai`), and logs to a CSV:
  cmd   : angle, seconds until the cell's desk reply (blank = no reply)
  mn    : GET cell state straight from the MN (http status, ms, opeLl)
  viaIN : GET the same state through the IN (http status, ms)
  cmdIN : POST a command through the IN (status, ms); the cell log shows whether it was applied
Phases come from the events file written by the shell script (epoch seconds). Use a fake run id (fk1) with fake_cell.py.
"""
import argparse, csv, json, math, threading, time
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from polagrid.onem2m import Client, _headers   # noqa: E402
from polagrid.zone import roles                # noqa: E402
from real_cell import Cell                     # noqa: E402

ANGLES = [45, 90, 45, 0, 60, 0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", default="fk1")
    ap.add_argument("--mn", type=int, default=1)
    ap.add_argument("--duration", type=float, default=510)
    ap.add_argument("--period", type=float, default=20)
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()
    mn_host, cse = f"http://127.0.0.1:{3000 + a.mn}", f"TinyIoT-mn{a.mn:03d}"
    via = f"http://127.0.0.1:3000/~/id-mn{a.mn:03d}/{cse}"
    o = roles(a.run)
    f = open(a.csv, "w", newline="")
    w, lock, end, n_in = csv.writer(f), threading.Lock(), time.time() + a.duration, [0]
    w.writerow(["t", "kind", "angle", "status", "ms", "extra"])

    def log(*row):
        with lock:
            w.writerow([f"{time.time():.3f}", *row]); f.flush()

    def get(url, origin):
        t0 = time.perf_counter()
        try:
            r = requests.get(url, headers=_headers(origin), timeout=5)
            return r.status_code, (time.perf_counter() - t0) * 1000, r
        except requests.RequestException as e:
            return type(e).__name__, (time.perf_counter() - t0) * 1000, None

    def probes():
        k = 0
        while time.time() < end:
            s, ms, r = get(f"{mn_host}/{cse}/{a.run}p0/state", o["view"])
            lvl = r.json()["cod:opeLl"]["opeLl"] if s == 200 else ""
            log("mn", "", s, f"{ms:.0f}", lvl)
            s, ms, _ = get(f"{via}/{a.run}p0/state", o["view"])
            log("viaIN", "", s, f"{ms:.0f}", "")
            k += 1
            if k % 6 == 0:                       # every 30 s: a command that must pass the IN
                n_in[0] += 1
                cell.lock.acquire()                  # wait for the controller's own command, or the probe would overwrite it in the cell's `la`
                t0 = time.perf_counter()
                body = {"m2m:cin": {"con": json.dumps({"cmd": f"{a.run}v{n_in[0]}", "angles": [cell.angle]})}}
                try:
                    r = requests.post(f"{via}/{a.run}ctl/grp/fopt", headers=_headers(o["ctl"], 4), data=json.dumps(body), timeout=10)
                    s = r.status_code
                except requests.RequestException as e:
                    s = type(e).__name__
                cell.lock.release()
                log("cmdIN", cell.angle, s, f"{(time.perf_counter() - t0) * 1000:.0f}", f"{a.run}v{n_in[0]}")
            time.sleep(5)

    cell = Cell(Client(mn_host, cse), a.run, 9791)
    cell.setup()
    threading.Thread(target=probes, daemon=True).start()
    i = 0
    try:
        while time.time() < end:
            tick = time.monotonic()
            ang = ANGLES[i % len(ANGLES)]; i += 1
            got = cell.send(ang, tries=1)        # tries=1: an MN error shows up as a failure row, not an endless retry
            log("cmd", ang, "ok" if got else "noreply", f"{got[0] * 1000:.0f}" if got else "", "")
            time.sleep(max(0.0, a.period - (time.monotonic() - tick)))
    except Exception as e:                        # the controller must not die; record and say so
        log("cmd", "", "CRASH", "", repr(e)[:120]); raise
    finally:
        cell.close()
        f.close()


if __name__ == "__main__":
    main()
