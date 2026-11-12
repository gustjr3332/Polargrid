"""sim/sandbox_receiver/receiver.py against a fake CSE on localhost (no docker, no sandbox)."""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sim" / "sandbox_receiver"))
import receiver   # noqa: E402


@pytest.fixture
def env(monkeypatch):
    """Fake CSE (records POSTs, answers `status`) and a receiver server wired to it."""
    seen, state = [], {"status": 201}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((self.path, self.headers, json.loads(body)))
            self.send_response(state["status"])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    cse = HTTPServer(("127.0.0.1", 0), Fake)
    monkeypatch.setenv("CSE_URL", f"http://127.0.0.1:{cse.server_port}")
    monkeypatch.setenv("CSE_BASE", "base1")
    monkeypatch.setenv("APP_NAME", "rx-app")
    cfg = receiver.config()
    rx = HTTPServer(("127.0.0.1", 0), receiver.make_handler(cfg))
    for s in (cse, rx):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield cfg, seen, state, f"http://127.0.0.1:{rx.server_port}"
    cse.shutdown()
    rx.shutdown()


def post(url, body, ri="ri-1"):
    req = urllib.request.Request(url, json.dumps(body).encode(), method="POST", headers={"X-M2M-RI": ri})
    return urllib.request.urlopen(req, timeout=5)


def test_provision_creates_ae_with_poa_then_container(env):
    cfg, seen, _, _ = env
    receiver.provision(cfg, tries=1, delay=0)
    (p1, h1, b1), (p2, h2, b2) = seen
    assert p1 == "/base1" and h1["Content-Type"] == "application/json;ty=2"
    assert h1["X-M2M-Origin"] == "CPolaGridSbxRx" and h1["X-M2M-RVI"] == "3"
    assert b1["m2m:ae"]["poa"] == ["http://rx-app:8080"] and b1["m2m:ae"]["rr"] is True and b1["m2m:ae"]["rn"] == "polagrid-sbxrx"
    assert p2 == "/base1/polagrid-sbxrx" and h2["Content-Type"] == "application/json;ty=3"
    assert b2["m2m:cnt"] == {"rn": "received", "mni": 20}


def test_409_does_not_abort_startup(env):
    cfg, seen, state, _ = env
    state["status"] = 409
    receiver.provision(cfg, tries=1, delay=0)
    assert len(seen) == 2


def test_provision_gives_up_with_clear_message(env):
    cfg, _, state, _ = env
    state["status"] = 500
    with pytest.raises(SystemExit, match="could not create AE"):
        receiver.provision(cfg, tries=2, delay=0)


def test_verification_request_gets_2000_and_stores_nothing(env):
    _, seen, _, rx = env
    r = post(rx, {"m2m:sgn": {"vrq": True, "sur": "x"}}, ri="v1")
    assert r.status == 200 and r.headers["X-M2M-RSC"] == "2000" and r.headers["X-M2M-RI"] == "v1"
    assert seen == []


def test_notification_is_stored_as_cin(env):
    _, seen, _, rx = env
    note = {"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": "hello"}}}, "sur": "x"}}
    r = post(rx, note)
    assert r.status == 200 and r.headers["X-M2M-RSC"] == "2000"
    (path, hdr, body), = seen
    assert path == "/base1/polagrid-sbxrx/received" and hdr["Content-Type"] == "application/json;ty=4"
    assert json.loads(body["m2m:cin"]["con"]) == note


def test_store_failure_still_answers_200_and_healthz_ok(env):
    _, _, state, rx = env
    state["status"] = 500
    assert post(rx, {"m2m:sgn": {"nev": {}}}).status == 200
    assert urllib.request.urlopen(rx + "/healthz", timeout=5).read() == b"ok"


def test_config_requires_base_or_sandbox_name(monkeypatch):
    monkeypatch.delenv("CSE_BASE", raising=False)
    monkeypatch.delenv("MEEP_SANDBOX_NAME", raising=False)
    with pytest.raises(SystemExit):
        receiver.config()
    monkeypatch.setenv("MEEP_SANDBOX_NAME", "sbx1")
    assert receiver.config()["cse"].endswith("/acme-cse-mn-mep1-sbx1")
