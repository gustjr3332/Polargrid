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

--mqtt talks oneM2M over MQTT instead of HTTP (needs paho-mqtt): requests go out as primitives on /oneM2M/req/<originator>/<cse-ri>/json
and the cell SUBscribes to its command container, so a notification triggers the command read; la is polled every 60 s as a
safety net (design: the MQTT design notes). --broker is where this script reaches the broker, --nu-broker how the CSE sees it.

    python3 tools/fake_cell.py --mqtt --broker 127.0.0.1:1883 --cse-ri id-mn001
"""
import argparse
import json
import math
import os
import queue
import random
import sys
import threading
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
MQTT_POLL_S = 60
RSC_TO_HTTP = {2000: 200, 2004: 200, 2001: 201, 4004: 404, 4103: 403, 4105: 409}   # design 2-6, anything else 500


class MqttResp:
    """The part of a requests.Response the polagrid client and fake_cell use."""

    def __init__(self, code, pc):
        self.status_code, self._pc = code, pc
        self.text = json.dumps(pc) if pc is not None else ""

    def json(self):
        return self._pc

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"MQTT request failed: {self.status_code}")


class MqttSession:
    """Drop-in for the requests.Session that polagrid.onem2m.Client uses (get/post/put/request), carrying oneM2M MQTT primitives.
    publish(topic, payload) sends; feed(topic, payload) is called with every message from the broker (paho thread).
    Responses are matched by rqi (the client's X-M2M-RI), a late one is dropped; notifications put True on self.notified."""

    def __init__(self, host, cse, cse_ri, publish, me=None):
        self.host, self.cse, self.cse_ri, self.publish, self.me = host, cse, cse_ri, publish, me   # me: our originator, filters notifications
        self.notified = queue.Queue()
        self._wait, self._lock = {}, threading.Lock()

    def feed(self, topic, payload):
        try:
            js = json.loads(payload)
        except ValueError:
            return
        if topic.startswith("/oneM2M/resp/"):
            if not topic.endswith(f"/{self.cse_ri}/json"):      # another CSE's reply
                return
            with self._lock:
                slot = self._wait.get(js.get("rqi"))
            if slot is not None:
                slot.put(js)
        elif self.me and topic != f"/oneM2M/req/{self.cse_ri}/{self.me}/json":   # a notification for another cell or run
            return
        elif "nev" in (js.get("m2m:sgn") or {}):        # a verification request (vrq) has no nev: not a command
            self.notified.put(True)

    def request(self, method, url, headers=None, data=None, timeout=30, **_):
        h = headers or {}
        ty = h.get("Content-Type", "").partition(";ty=")[2]
        prim = {"op": {"POST": 1, "GET": 2, "PUT": 3}[method], "to": url[len(self.host) + 1:], "fr": h["X-M2M-Origin"],
                "rqi": h["X-M2M-RI"], "rvi": "3"}
        if method == "POST" and ty:
            prim["ty"] = int(ty)
        if data:
            prim["pc"] = json.loads(data)
        slot = queue.Queue(1)
        with self._lock:
            self._wait[prim["rqi"]] = slot
        try:
            self.publish(f"/oneM2M/req/{prim['fr'].replace('/', ':')}/{self.cse_ri}/json", json.dumps(prim))
            try:
                js = slot.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"no MQTT response for {method} {prim['to']}") from None
        finally:
            with self._lock:
                self._wait.pop(prim["rqi"], None)
        return MqttResp(RSC_TO_HTTP.get(js.get("rsc"), 500), js.get("pc"))

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)


def mqtt_session(broker, host, cse, cse_ri, me=None):
    """MqttSession on a paho client (1.x or 2.x), subscribed to our responses and notifications. paho is only imported here."""
    import paho.mqtt.client as mqtt
    name = f"fake-cell-{os.getpid()}-{random.getrandbits(32):08x}"   # two cells on one broker must not share a client id
    try:
        cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=name)   # paho 2.x
    except AttributeError:
        cl = mqtt.Client(client_id=name)                                     # paho 1.x
    s = MqttSession(host, cse, cse_ri, lambda t, p: cl.publish(t, p, qos=0), me)
    cl.on_connect = lambda c, u, *a: (c.subscribe(f"/oneM2M/resp/+/{cse_ri}/json"), c.subscribe(f"/oneM2M/req/{cse_ri}/+/json"))
    cl.on_message = lambda c, u, m: s.feed(m.topic, m.payload)
    h, _, port = broker.partition(":")
    cl.connect(h, int(port or 1883), keepalive=30)
    cl.loop_start()
    return s


def subscribe(c, run, index, nu):
    """SUB on {run}p<index>/command that notifies `nu`; a 409 (SUB already there) updates nu, it may be an old one."""
    me, cell = f"C{run}p{index}", f"{run}p{index}"
    sub = {"m2m:sub": {"rn": "s", "nu": [nu], "enc": {"net": [3]}, "nct": 1}}
    if c.post(f"{cell}/command", me, sub, 23, exist_ok=True) is None:
        c.put(f"{cell}/command/s", me, {"m2m:sub": {"nu": [nu]}})


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
    ap.add_argument("--mqtt", action="store_true", help="oneM2M over MQTT (paho-mqtt) instead of HTTP")
    ap.add_argument("--broker", default="127.0.0.1:1883", help="with --mqtt: broker host[:port] as this script reaches it")
    ap.add_argument("--cse-ri", default="id-mn001", help="with --mqtt: CSE_BASE_RI of the MN (topics)")
    ap.add_argument("--nu-broker", default="127.0.0.1:1883", help="with --mqtt: broker as the MN sees it, same text as its MQTT_HOST:PORT")
    ap.add_argument("--lamp", type=float, default=800.0, help="fake cell-sensor lux with the disc open")
    ap.add_argument("--leak", type=float, default=15.0, help="fake cell-sensor lux with the disc closed")
    a = ap.parse_args()
    c, run, rng = Client(a.host, a.cse), a.run, np.random.default_rng(a.index)
    session = None
    if a.mqtt:
        from polagrid.onem2m import _local
        session = _local.s = mqtt_session(a.broker, a.host, a.cse, a.cse_ri, f"C{run}p{a.index}")   # Client now sends over MQTT, same calls
    idx, col = a.index, a.index if a.col is None else a.col
    me, env, cell_rn = f"C{run}p{idx}", roles(run)["env"], f"{run}p{idx}"
    disc = target = 0.0
    last_cmd = pending = None
    published, ready, fails = None, False, 0
    last_poll = last_report = last_rx = t_prev = time.monotonic()
    privacy = False
    poll_s = MQTT_POLL_S if a.mqtt else POLL_S
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
                if a.mqtt:
                    subscribe(c, run, idx, f"mqtt://{a.nu_broker}/{me}/json")
                ready, fails, published, last_poll = True, 0, None, 0.0   # poll at once
                print("[FAKE cell] CSE ready")
            while session and not session.notified.empty():   # a notification: read la now, through the same code as a poll
                session.notified.get()
                if last_cmd is None:
                    last_cmd = ""               # a notification is a fresh command, not the old one left from before boot
                last_poll = -poll_s
            if now - last_poll >= poll_s:
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
