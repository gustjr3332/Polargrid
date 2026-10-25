"""Bluetooth bridge for the real cell built with `pio run -e bt` (sw/actuator). Run with Windows Python next to the paired
BT COM port. It does on the CSE what the Wi-Fi firmware does (and fake_cell.py imitates): provisions {run}env and {run}p0,
polls {run}p0/command/la every 2 s, PUTs state, posts the desk reply and the 10 s readings. The disc and the sensors are
on the BT link, line protocol in sw/actuator/src/cell_logic.h. real_cell.py and the CSE resources do not change.

    pip install pyserial
    python tools/bt_bridge.py --port COM5 --run real1

After each CSE reply the bridge sends PING; the cell opens by itself (not in privacy mode) after 60 s without one, so a
lost BT link, a stopped bridge and a silent CSE all end with the disc open. A lost port is reopened every 3 s.
"""
import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from polagrid.onem2m import Client, _headers, con as cin_con   # noqa: E402
from polagrid.zone import roles                                 # noqa: E402
from fake_cell import POLL_S, provision                         # noqa: E402
from real_cell import CSE_ERRORS, backoff_s                     # noqa: E402

APPLY_WAIT_S = 25   # firmware APPLY_WAIT_MS: a desk reply later than this answers nothing (controller waits 30 s)


class Bridge:
    """CSE side of one cell. `ser` is the open port (pyserial or a fake with read/write/in_waiting), None while lost."""

    def __init__(self, c, run, index):
        self.c, self.run = c, run
        self.me, self.env, self.cell = f"C{run}p{index}", roles(run)["env"], f"{run}p{index}"
        self.idx, self.ser, self.buf = index, None, b""
        self.last_cmd = self.pending = self.published = self.level = None
        self.pending_t = 0.0

    def send(self, line):
        if self.ser is None:
            return
        try:
            self.ser.write((line + "\n").encode())
        except OSError as e:          # serial.SerialException is an OSError
            self.lost(e)

    def lines(self):
        """Complete lines read from the cell so far."""
        if self.ser is None:
            return []
        try:
            self.buf += self.ser.read(self.ser.in_waiting or 1)
        except OSError as e:
            self.lost(e)
            return []
        *done, self.buf = self.buf.split(b"\n")
        return [d.decode(errors="replace").strip() for d in done if d.strip()]

    def lost(self, e):
        print(f"[bridge] BT port lost: {str(e)[:80]}")
        try:
            self.ser.close()
        except OSError:
            pass
        self.ser, self.buf = None, b""

    def poll(self, now):
        """One GET of command/la, like netTask. Returns False when the cell must be provisioned again (403)."""
        r = self.c._session().get(f"{self.c.host}/{self.c.cse}/{self.cell}/command/la", headers=_headers(self.me), timeout=10)
        self.send("PING")
        if r.status_code == 403:
            return False
        if r.status_code == 404 and self.last_cmd is None:
            self.last_cmd = ""        # no command yet, so the first one that appears is new
        if r.status_code != 200:
            return True
        con = cin_con(r.json()["m2m:cin"])
        try:
            cmd, want = con["cmd"], float(con["angles"][self.idx])
        except (KeyError, IndexError, TypeError, ValueError):
            print(f"[bridge] malformed command ignored: {str(con)[:80]}")
            return True
        if self.last_cmd is None:     # the first command seen after start is an old one: remember it only
            self.last_cmd = cmd
            print(f"[bridge] SKIP old command {cmd} (the heartbeat sends a fresh one)")
        elif cmd and cmd != self.last_cmd:
            self.last_cmd, self.pending, self.pending_t = cmd, cmd, now
            priv = con.get("mode") == "privacy"
            if priv or (math.isfinite(want) and -0.5 <= want <= 90.5):
                self.send("PRIV 1" if priv else "PRIV 0")
                self.send(f"A 0 {90.0 if priv else want:.1f}")
            else:
                self.send("FAILSAFE")   # nonsense angle: the cell opens and still answers at 0
            print(f"[bridge] {cmd}: {'privacy' if priv else want}")
        return True

    def publish(self):
        """PUT state when the cell's level differs from the CSE (also after a new setup, whose state starts at 100)."""
        if self.level is not None and self.level != self.published:
            self.c.put(f"{self.cell}/state", self.me, {"cod:opeLl": {"opeLl": self.level}})
            self.published = self.level

    def line(self, text, now):
        """One line from the cell."""
        kind, *v = text.split()
        try:
            vals = [float(x) for x in v]
        except ValueError:
            vals = []
        if kind == "POS" and len(vals) == 1:
            self.level = round(100 * math.cos(math.radians(vals[0])) ** 2)
            self.publish()
        elif kind == "DESK" and len(vals) == 1:
            if self.pending and now - self.pending_t <= APPLY_WAIT_S:
                self.c.create(f"{self.run}env/desks", self.env, {"cmd": self.pending, "lux": [vals[0]]})
            self.pending = None
        elif kind == "LUX" and len(vals) == 2:
            cell, desk = vals
            if desk >= 0:
                self.c.create(f"{self.run}env/desks", self.env, {"cmd": f"t{int(time.time())}", "lux": [desk]})
            if cell >= 0:
                self.c.create(f"{self.cell}/lux", self.me, {"lux": cell})
        else:
            print(f"[cell] {text}")


def main():
    ap = argparse.ArgumentParser(description="Bluetooth bridge: real cell (env:bt) <-> MN-CSE over HTTP")
    ap.add_argument("--port", required=True, help="BT serial port of the paired polagrid-cell, e.g. COM5")
    ap.add_argument("--host", default="http://127.0.0.1:3001")
    ap.add_argument("--cse", default="TinyIoT-mn001")
    ap.add_argument("--run", default="real1")
    ap.add_argument("--index", type=int, default=0, help="CELL_INDEX")
    ap.add_argument("--row", type=int, default=0, help="CELL_ROW (0 = top)")
    ap.add_argument("--col", type=int, default=None, help="CELL_COL (0 = left), default = --index")
    a = ap.parse_args()
    import serial                     # only here, so the tests run without pyserial
    b = Bridge(Client(a.host, a.cse), a.run, a.index)
    col = a.index if a.col is None else a.col
    ready, fails, last_poll, retry_at = False, 0, 0.0, 0.0
    print(f"[bridge] {a.port} <-> {a.host}/{a.cse} run {a.run} cell p{a.index}")
    while True:
        now = time.monotonic()
        if b.ser is None and now >= retry_at:
            try:
                b.ser = serial.Serial(a.port, 115200, timeout=0.05, write_timeout=2)
                print(f"[bridge] {a.port} open")
            except (serial.SerialException, OSError) as e:
                print(f"[bridge] cannot open {a.port}: {str(e)[:80]}; again in 3 s")
                retry_at = now + 3
        if b.ser is None:
            time.sleep(0.05)
        try:
            for text in b.lines():
                b.line(text, now)
            if not ready:
                provision(b.c, a.run, a.index, a.row, col)
                ready, fails, b.published, last_poll = True, 0, None, 0.0
                print("[bridge] CSE ready")
            if now - last_poll >= POLL_S:
                last_poll = now
                ready = b.poll(now)
            b.publish()
        except CSE_ERRORS as e:
            fails += 1
            print(f"[bridge] CSE error: {str(e)[:100]}; again in {backoff_s(fails)} s")
            time.sleep(backoff_s(fails))
            ready = False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
