"""Reproduces: tinyIoT crashes (SIGSEGV) when a GRP fan-out and other CIN creations run at the same time.

N AEs each have a `command` container with a subscription and an `angle` container. One GRP holds all
`command` containers. Every round posts one CIN to <grp>/fopt; each AE reacts to its notification by posting
a CIN to its own `angle` container, so N creations race with the rest of the fan-out. Because some tinyIoT
versions never send the notification (see bug 3), N more writers are also started at the same moment the
fan-out request is sent, so the race does not depend on notifications.

Needs only `requests`. Run on the machine where the CSE runs (the CSE must reach 127.0.0.1:PORT):
    python3 concurrent_fopt_crash.py [CSE_BASE_URL] [N=12] [ROUNDS=100]
Exit code 1 and "CSE died" = reproduced. Tested on seslabSJU/tinyIoT 832205f, MN-CSE, SQLite.
"""
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3001/TinyIoT-mn001"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 12
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 100
PORT = 9900
RUN = f"x{int(time.time()) % 100000}"
CSE = BASE.rstrip("/").rsplit("/", 1)[1]


def post(path, origin, body, ty):
    h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3",
         "Accept": "application/json", "Content-Type": f"application/json;ty={ty}"}
    r = requests.post(f"{BASE}/{path}".rstrip("/"), headers=h, data=json.dumps(body), timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"POST {path} -> {r.status_code} {r.text[:150]}")


def cin(path, origin, content):
    post(path, origin, {"m2m:cin": {"con": json.dumps(content)}}, 4)


def _safe_cin(path, origin, content):
    try:
        cin(path, origin, content)
    except requests.RequestException:
        pass


got = {}                       # round -> number of notifications received
lock = threading.Lock()
writers = []


class Notify(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.send_header("Content-Length", "0")
        self.end_headers()
        try:
            con = json.loads(json.loads(body)["m2m:sgn"]["nev"]["rep"]["m2m:cin"]["con"])
        except (KeyError, ValueError):
            return                                       # subscription verification request
        i = int(self.path.strip("/")[1:])
        with lock:
            got[con["round"]] = got.get(con["round"], 0) + 1

        def write():                                     # the AE reports its new angle right away
            try:
                cin(f"{RUN}p{i}/angle", f"C{RUN}p{i}", {"round": con["round"]})
            except requests.RequestException:
                pass
        t = threading.Thread(target=write)
        t.start()
        writers.append(t)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", PORT), Notify)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()

for i in range(N):
    o, rn, nu = f"C{RUN}p{i}", f"{RUN}p{i}", f"http://127.0.0.1:{PORT}/p{i}"
    post("", o, {"m2m:ae": {"rn": rn, "api": "Nrepro", "rr": True, "srv": ["3"], "poa": [nu]}}, 2)
    post(rn, o, {"m2m:cnt": {"rn": "command", "mni": 10}}, 3)
    post(rn, o, {"m2m:cnt": {"rn": "angle", "mni": 10}}, 3)
    post(f"{rn}/command", o, {"m2m:sub": {"rn": "s", "nu": [nu], "enc": {"net": [3]}, "nct": 1}}, 23)
post("", "CAdmin", {"m2m:grp": {"rn": f"{RUN}grp", "mt": 3, "mnm": N,
                                "mid": [f"{CSE}/{RUN}p{i}/command" for i in range(N)]}}, 9)
print(f"set up {N} AEs and one GRP on {BASE}")

for k in range(ROUNDS):
    try:
        for i in range(N):                               # writers that do not wait for a notification
            t = threading.Thread(target=lambda i=i: _safe_cin(f"{RUN}p{i}/angle", f"C{RUN}p{i}", {"round": k}))
            t.start()
            writers.append(t)
        cin(f"{RUN}grp/fopt", "CAdmin", {"round": k})
        end = time.time() + 2
        while time.time() < end and got.get(k, 0) < N:
            time.sleep(0.01)
        for t in list(writers):
            t.join()
        writers.clear()
    except requests.RequestException as e:
        print(f"CSE died in round {k}: {type(e).__name__}")
        sys.exit(1)
    if got.get(k, 0) < N:
        print(f"round {k}: only {got.get(k, 0)}/{N} notifications")
print(f"no crash in {ROUNDS} rounds")
