"""Minimal repro: resources created through GRP `fopt` do not trigger subscription notifications.

Creates one AE with a `command` container and a subscription, a GRP containing that container, then posts one CIN
directly and one CIN through <grp>/fopt, and prints the notifications the receiver got after each step.
Expected: one notification after the direct CIN and one after the fopt CIN. tinyIoT 832205f and c140495 send
none after the fopt CIN.

Needs `requests`; run on the machine where the CSE runs (it must reach 127.0.0.1:9910):
    python3 fopt_no_notification.py        (CSE: http://127.0.0.1:3001/TinyIoT-mn001, edit BASE below)
"""
import json, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
BASE = "http://127.0.0.1:3001/TinyIoT-mn001"; PORT = 9910; RUN = f"n{int(time.time()) % 100000}"
bodies = []
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_POST(self):
        b = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        bodies.append((self.path, b.decode()[:400]))
        self.send_response(200); self.send_header("X-M2M-RSC", "2000"); self.send_header("Content-Length", "0"); self.end_headers()
    def log_message(self, *a): pass
s = ThreadingHTTPServer(("127.0.0.1", PORT), H); s.daemon_threads = True
threading.Thread(target=s.serve_forever, daemon=True).start()
def post(path, o, body, ty):
    h = {"X-M2M-Origin": o, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3", "Accept": "application/json", "Content-Type": f"application/json;ty={ty}"}
    r = requests.post(f"{BASE}/{path}".rstrip("/"), headers=h, data=json.dumps(body), timeout=30); return r.status_code
o, rn, nu = f"C{RUN}", f"{RUN}a", f"http://127.0.0.1:{PORT}/x"
print("ae", post("", o, {"m2m:ae": {"rn": rn, "api": "Nt", "rr": True, "srv": ["3"], "poa": [nu]}}, 2))
print("cnt", post(rn, o, {"m2m:cnt": {"rn": "command", "mni": 10}}, 3))
print("sub", post(f"{rn}/command", o, {"m2m:sub": {"rn": "s", "nu": [nu], "enc": {"net": [3]}, "nct": 1}}, 23))
time.sleep(1); print("after sub create, bodies:", len(bodies)); [print("  ", b) for b in bodies]; bodies.clear()
print("grp", post("", "CAdmin", {"m2m:grp": {"rn": f"{RUN}g", "mt": 3, "mnm": 1, "mid": [f"TinyIoT-mn001/{rn}/command"]}}, 9))
print("direct cin", post(f"{rn}/command", o, {"m2m:cin": {"con": "direct"}}, 4)); time.sleep(1)
print("after direct CIN, bodies:", len(bodies)); [print("  ", b) for b in bodies]; bodies.clear()
print("fopt cin", post(f"{RUN}g/fopt", "CAdmin", {"m2m:cin": {"con": "viafopt"}}, 4)); time.sleep(1)
print("after fopt CIN, bodies:", len(bodies)); [print("  ", b) for b in bodies]
