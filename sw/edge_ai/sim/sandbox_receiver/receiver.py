"""Tiny oneM2M notification receiver for the ETSI MEC Sandbox (stdlib only).

Registers an AE with a poa on the sandbox MN-CSE, then stores every received
notification as a CIN in <AE>/received so it can be read from outside.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def config():
    env = os.environ
    sbx = env.get("MEEP_SANDBOX_NAME")
    base = env.get("CSE_BASE") or (f"acme-cse-mn-{env.get('MEP', 'mep1')}-{sbx}" if sbx else None)
    if not base:
        sys.exit("error: set CSE_BASE or MEEP_SANDBOX_NAME (injected by the sandbox)")
    port = int(env.get("PORT", "8080"))
    return {
        "cse": env.get("CSE_URL", "http://mep1-meep-acme-mn-cse").rstrip("/") + "/" + base,
        "port": port,
        "poa": f"http://{env.get('APP_NAME', 'polagrid-rx')}:{port}",
        "ae": env.get("AE_RN", "polagrid-sbxrx"),
        "origin": env.get("ORIGINATOR", "CPolaGridSbxRx"),
    }


def create(cfg, url, ty, body):
    """POST a create request; return the HTTP status (409 = already exists, fine)."""
    req = urllib.request.Request(url, json.dumps(body).encode(), method="POST", headers={
        "X-M2M-Origin": cfg["origin"], "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3",
        "Content-Type": f"application/json;ty={ty}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def provision(cfg, tries=10, delay=3.0):
    ae = {"m2m:ae": {"rn": cfg["ae"], "api": "Npolagrid", "rr": True, "srv": ["3"], "poa": [cfg["poa"]]}}
    cnt = {"m2m:cnt": {"rn": "received", "mni": 20}}
    steps = [("AE", cfg["cse"], 2, ae), ("container", f"{cfg['cse']}/{cfg['ae']}", 3, cnt)]
    for name, url, ty, body in steps:
        for i in range(tries):
            try:
                code = create(cfg, url, ty, body)
            except OSError as e:
                code = f"unreachable ({e})"
            print(f"create {name}: {code}", flush=True)
            if code in (201, 409):
                break
            if i < tries - 1:
                time.sleep(delay)
        else:
            sys.exit(f"error: could not create {name} on {cfg['cse']} after {tries} tries")


def make_handler(cfg):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code=200, rsc=True, text=b""):
            self.send_response(code)
            if rsc:
                self.send_header("X-M2M-RSC", "2000")
                self.send_header("X-M2M-RI", self.headers.get("X-M2M-RI", ""))
                self.send_header("X-M2M-RVI", self.headers.get("X-M2M-RVI", "3"))
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            self.wfile.write(text)

        def do_GET(self):
            self.reply(200 if self.path == "/healthz" else 404, rsc=False, text=b"ok" if self.path == "/healthz" else b"")

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
            try:
                sgn = json.loads(raw).get("m2m:sgn") or {}
            except (ValueError, AttributeError):
                sgn = {}
            if not sgn.get("vrq"):
                print("notification:", raw[:500], flush=True)
                body = {"m2m:cin": {"con": raw[:4000]}}
                try:
                    code = create(cfg, f"{cfg['cse']}/{cfg['ae']}/received", 4, body)
                    if code != 201:
                        print(f"store failed: {code}", flush=True)
                except OSError as e:
                    print(f"store failed: {e}", flush=True)
            self.reply()

        def log_message(self, *a):
            pass

    return Handler


if __name__ == "__main__":
    cfg = config()
    provision(cfg)
    print(f"listening on 0.0.0.0:{cfg['port']}, poa {cfg['poa']}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", cfg["port"]), make_handler(cfg)).serve_forever()
