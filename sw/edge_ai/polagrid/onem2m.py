"""Minimal oneM2M HTTP client for tinyIoT and a notification receiver.

Resource contents (CIN `con`) are JSON strings; create() and latest() convert to and from dicts.
"""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

_local = threading.local()


def _headers(origin, ty=None):
    ct = "application/json" + (f";ty={ty}" if ty else "")
    return {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3",
            "Accept": "application/json", "Content-Type": ct}


class Client:
    """Talks to one CSE, e.g. Client("http://127.0.0.1:3001", "TinyIoT-mn001"). Paths are relative to the CSE base."""

    def __init__(self, host, cse):
        self.host, self.cse = host, cse

    def _session(self):
        if not hasattr(_local, "s"):
            _local.s = requests.Session()
        return _local.s

    def post(self, path, origin, body, ty):
        r = self._session().post(f"{self.host}/{self.cse}/{path}".rstrip("/"), headers=_headers(origin, ty),
                                 data=json.dumps(body), timeout=30)
        if not 200 <= r.status_code < 300:
            raise RuntimeError(f"POST {path} ty={ty}: {r.status_code} {r.text[:200]}")
        return r

    def put(self, path, origin, body):
        r = self._session().put(f"{self.host}/{self.cse}/{path}", headers=_headers(origin),
                                data=json.dumps(body), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"PUT {path}: {r.status_code} {r.text[:200]}")
        return r

    def discover(self, origin, **filters):
        """Resource paths under the CSE base matching the filter criteria, e.g. discover(o, lbl="x", ty=3)."""
        q = "&".join(f"{k}={v}" for k, v in {"fu": 1, **filters}.items())
        r = self._session().get(f"{self.host}/{self.cse}?{q}", headers=_headers(origin), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"discover {q}: {r.status_code} {r.text[:200]}")
        return r.json().get("m2m:uril", [])

    def code(self, method, path, origin, body=None, ty=None):
        """HTTP status of one request, without raising (for access-control checks)."""
        return self._session().request(method, f"{self.host}/{self.cse}/{path}", headers=_headers(origin, ty),
                                       data=json.dumps(body) if body else None, timeout=30).status_code

    def create(self, path, origin, content, ty=4):
        """Create a CIN holding `content` (a dict) under path."""
        return self.post(path, origin, {"m2m:cin": {"con": json.dumps(content)}}, ty)

    def latest(self, path, origin):
        """Content of the newest CIN in the container at path."""
        r = self._session().get(f"{self.host}/{self.cse}/{path}/la", headers=_headers(origin), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"GET {path}/la: {r.status_code} {r.text[:200]}")
        return json.loads(r.json()["m2m:cin"]["con"])


class Receiver:
    """HTTP server for oneM2M notifications. handler(path, content) runs after the 200 reply."""

    def __init__(self, port, handler):
        class Handler(BaseHTTPRequestHandler):
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
                    return                      # subscription verification request, nothing to handle
                handler(self.path.strip("/"), con)

            def log_message(self, *args):
                pass

        self.port = port
        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True

    def url(self, name):
        return f"http://127.0.0.1:{self.port}/{name}"

    def start(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
