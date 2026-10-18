"""Record the HTTP requests zone.py sends for one virtual cell (no CSE needed, requests.Session is faked).
python -E tests_host/zone_capture.py ../edge_ai > tests_host/zone_requests.txt   (from sw/actuator)
Compare with ./test_onem2m --print (same "METHOD path origin ty body" lines)."""
import json, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
import polagrid.onem2m as om
import polagrid.zone as zone
from polagrid.physics import Room, KST

log = []

class Resp:
    def __init__(self, body, code=201):
        self.status_code, self._b, self.text = code, body, json.dumps(body)
    def json(self): return self._b

class Sess:
    def _rec(self, m, url, headers, data):
        path = url.split("/TinyIoT-mn001", 1)[1].lstrip("/")
        ct = headers["Content-Type"]
        ty = int(ct.split("ty=")[1]) if "ty=" in ct else 0
        log.append(f"{m} {path} {headers['X-M2M-Origin']} {ty} {data or ''}")
        if data and "\"rn\"" in data and "m2m:acp" in data:
            return Resp({"m2m:acp": {"ri": "RI-" + json.loads(data)["m2m:acp"]["rn"], "pv": {"acr": []}}})
        return Resp({"m2m:acp": {"pv": {"acr": []}}, "m2m:uril": ["TinyIoT-mn001/real1p0/command"]}, 200 if m != "POST" else 201)
    def post(self, url, headers=None, data=None, timeout=None): return self._rec("POST", url, headers, data)
    def put(self, url, headers=None, data=None, timeout=None): return self._rec("PUT", url, headers, data)
    def get(self, url, headers=None, timeout=None): return self._rec("GET", url, headers, None)

om.requests.Session = Sess
c = om.Client("http://127.0.0.1:3001", "TinyIoT-mn001")
z = zone.Zone(c, Room(rows=1, cols=1), "real1", 9790)
z.setup()
print("## zone.setup"); print("\n".join(log)); log.clear()
ctl = zone.Controller(c, "real1", 9791)
ctl.setup(1); print("## controller.setup"); print("\n".join(log)); log.clear()
zone.WAIT_S = 0.1
try: ctl.command([45])
except TimeoutError: pass
print("## controller.command"); print("\n".join(log)); log.clear()
z.t = datetime(2026, 11, 5, 12, tzinfo=KST)
z._on_command("p0", {"cmd": "real1c1", "angles": [45.0]})
print("## cell applies command"); print("\n".join(log))
