"""MEC services through oneM2M: a bridge AE on the zone MN-CSE.

tinyIoT cannot run the Sandbox MEC-IPE (it rejects the IPE's FlexContainers), so this AE does the IPE's job in a
smaller form. It reads the MEC platform over Mp1 (MEC 011: the service list with its state, and the platform
time) and writes what it reads into two containers on the MN-CSE as labelled content instances. Other AEs find
the containers by label and read or subscribe to them. They never call the MEC API.

Usage (from sw/edge_ai):
  python tools/mec_bridge.py bridge <mep_base> [--cse http://127.0.0.1:3001/TinyIoT-mn001] [--run mec] [--every 30] [--once] [--insecure]
  python tools/mec_bridge.py read [--cse ...] [--run mec]
  python tools/mec_bridge.py watch [--cse ...] [--run mec] [--port 9795] [--for 0]
    mep_base: https://<sandbox-host>/<sandbox-key>/mep1  (session URL, do not commit or paste into results)
    --insecure: skip TLS verification (the hosted Sandbox has a self-signed certificate)
    read: what a consumer sees, as the zone's viewer originator, through the CSE only
    watch: the zone controller subscribes to the service list and prints each change the CSE notifies
           (--for N stops after N seconds, 0 runs until Ctrl-C; the CSE must reach 127.0.0.1:<port>)
"""
import argparse
import sys
import threading
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid.onem2m import Client, Receiver                                              # noqa: E402
from polagrid.zone import ALL, DISC, C, N, R, grant_discovery, make_acp, remote, roles  # noqa: E402

SERVICES, TIME = "mec_service_mgmt/v1/services", "mec_app_support/v2/timing/current_time"


def origin(run):
    return f"C{run}mec"


def label(run, name):
    return f"polagrid/{run}/mec/{name}"


def service_rows(services, mep_base=""):
    """MEC 011 ServiceInfo list -> rows sorted by name. Endpoints are stored relative to the MEP base, because
    the base holds the Sandbox session key, which must not end up in the CSE or in a results file."""
    rows = []
    for s in services:
        uris = ((s.get("transportInfo") or {}).get("endpoint") or {}).get("uris") or []
        rows.append({"name": s.get("serName"), "id": s.get("serInstanceId"), "state": s.get("state"),
                     "version": s.get("version"), "paths": [u.replace(mep_base, "", 1) for u in uris]})
    return sorted(rows, key=lambda r: str(r["name"]))


def setup(c, run):
    """Bridge AE with two containers. The zone's viewer may read, be notified and discover. The controller may also
    create, because tinyIoT asks for CREATE before it accepts a <subscription>, the same rights it has on env/desks."""
    o, r = origin(run), roles(run)
    grant_discovery(c)
    acp = make_acp(c, f"{run}mecacp", [([o], ALL), (remote(r["ctl"]), C | R | N | DISC), (remote(r["view"]), R | N | DISC)],
                   exist_ok=True)
    c.post("", o, {"m2m:ae": {"rn": f"{run}mec", "api": "Npolagrid", "rr": False, "srv": ["3"]}}, 2, exist_ok=True)
    for name in ("services", "time"):
        c.post(f"{run}mec", o, {"m2m:cnt": {"rn": name, "mni": 10, "acpi": [acp], "lbl": [label(run, name)]}}, 3,
               exist_ok=True)


def step(c, run, fetch, last=None, mep_base=""):
    """One poll of the MEC platform. The service list is written only when it changed; the time every poll.
    fetch(path) returns the parsed JSON of <mep_base>/<path>. Returns the service rows for the next call."""
    rows = service_rows(fetch(SERVICES), mep_base)
    if rows != last:
        c.create(f"{run}mec/services", origin(run), {"services": rows})
    t = fetch(TIME)
    c.create(f"{run}mec/time", origin(run), {"seconds": t["seconds"], "nanoSeconds": t.get("nanoSeconds", 0),
                                             "status": t.get("timeSourceStatus")})
    return rows


def read(c, run):
    """What a consumer gets through oneM2M alone: discover both containers by label, then read the newest CIN."""
    viewer = roles(run)["view"]
    out = {}
    for name in ("services", "time"):
        found = c.discover(viewer, lbl=label(run, name), ty=3)
        if len(found) != 1:
            raise RuntimeError(f"expected one container labelled {label(run, name)}, found {len(found)}")
        out[name] = c.latest(found[0].split("/", 1)[1], viewer)    # discovery returns <cse>/<path>
    return out


def changes(old, new):
    """Lines describing what changed between two service lists ({name: state} each)."""
    return [f"{n}: {old.get(n, 'new')} -> {new.get(n, 'gone')}" for n in sorted(old.keys() | new.keys())
            if old.get(n) != new.get(n)]


def watch(c, run, port, seconds=0, out=print):
    """Consumer side, as the zone controller: find the service list by label, subscribe to it, and report every
    change the CSE notifies. No MEC call."""
    me = roles(run)["ctl"]
    found = c.discover(me, lbl=label(run, "services"), ty=3)
    if len(found) != 1:
        raise RuntimeError(f"expected one container labelled {label(run, 'services')}, found {len(found)}")
    path = found[0].split("/", 1)[1]
    last = {s["name"]: s["state"] for s in c.latest(path, me)["services"]}
    out(f"[watch] {len(last)} services known, subscribing to {path}")

    def on(_, con):
        if not isinstance(con.get("services"), list):    # anyone with CREATE on the container can write here
            out("[watch] ignored a notification without a service list")
            return
        now = {s["name"]: s["state"] for s in con["services"]}
        for line in changes(last, now) or ["notified, no change"]:
            out(f"[watch] {line}")
        last.clear()
        last.update(now)

    rx = Receiver(port, on)
    rx.start()
    c.post(path, me, {"m2m:sub": {"rn": f"{run}watch", "nu": [rx.url("mec")], "enc": {"net": [3]}, "nct": 1}}, 23,
           exist_ok=True)
    try:
        time.sleep(seconds) if seconds else threading.Event().wait()
    finally:
        rx.stop()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mode", choices=["bridge", "read", "watch"])
    p.add_argument("mep_base", nargs="?")
    p.add_argument("--cse", default="http://127.0.0.1:3001/TinyIoT-mn001")
    p.add_argument("--run", default="mec")
    p.add_argument("--every", type=float, default=30)
    p.add_argument("--once", action="store_true")
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--port", type=int, default=9795)
    p.add_argument("--for", dest="seconds", type=float, default=0)
    a = p.parse_args()
    host, cse = a.cse.rsplit("/", 1)
    c = Client(host, cse)

    if a.mode == "watch":
        watch(c, a.run, a.port, a.seconds, lambda line: print(line, flush=True))
        return

    if a.mode == "read":
        got = read(c, a.run)
        for s in got["services"]["services"]:
            print(f"{s['name']:<18}{s['state']:<10}{s['version']:<8}{' '.join(s['paths'])}")
        print(f"platform time {got['time']['seconds']} ({got['time']['status']}), local clock {int(time.time())}")
        return

    if not a.mep_base:
        p.error("bridge needs <mep_base>")
    base = a.mep_base.rstrip("/")
    if a.insecure:
        requests.packages.urllib3.disable_warnings()

    def fetch(path):
        r = requests.get(f"{base}/{path}", timeout=15, verify=not a.insecure)
        r.raise_for_status()
        return r.json()

    setup(c, a.run)
    rows = None
    while True:
        rows = step(c, a.run, fetch, rows, base)
        print(f"[bridge] {len(rows)} services, {sum(r['state'] == 'ACTIVE' for r in rows)} active", flush=True)
        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
