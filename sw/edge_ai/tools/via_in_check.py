"""Do the roles still work THROUGH the IN after tools/harden_acp.py? Prints status codes, exit 1 on a surprise.

A client of the IN reaches an MN as /~/<csi>/<cse>/..., and the IN forwards the originator as /tinyiot/<originator>.
Checks on MN 1 (run id of a cell on it with --run, default real1 = fake_cell.py / the real cell):
  CAdmin creates and deletes a test ACP at the CSE base      -> must work (this is how zones are set up through the IN)
  C<run>view reads the cell's state                           -> must work (the demo page / the phone app)
  a stranger reads the CSE base and the cell's state          -> must be refused after hardening

    python3 tools/via_in_check.py --run real1
"""
import argparse
import json
import sys
import uuid

import requests

IN = "http://127.0.0.1:3000"
ADMINS = ["CAdmin", "/tinyiot/CAdmin"]   # the admin directly and as the IN forwards it


def call(method, url, origin, body=None, ty=None):
    h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3", "Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
    return requests.request(method, url, headers=h, data=json.dumps(body) if body is not None else None, timeout=20).status_code


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", default="real1")
    ap.add_argument("--mn", type=int, default=1)
    ap.add_argument("--hardened", action="store_true", help="also require that a stranger is refused")
    a = ap.parse_args()
    base = f"{IN}/~/id-mn{a.mn:03d}/TinyIoT-mn{a.mn:03d}"
    rn = f"viaincheck{uuid.uuid4().hex[:6]}"
    acp = {"m2m:acp": {"rn": rn, "pv": {"acr": [{"acor": ADMINS, "acop": 63}]}, "pvs": {"acr": [{"acor": ADMINS, "acop": 63}]}}}
    results = {
        "admin creates an ACP at the base": (call("POST", base, "CAdmin", acp, 1), (201,)),
        "viewer reads the cell state": (call("GET", f"{base}/{a.run}p0/state", f"C{a.run}view"), (200,)),
    }
    results["admin deletes the test ACP"] = (call("DELETE", f"{base}/{rn}", "CAdmin"), (200,))
    stranger = "Cstranger"
    s_base, s_state = call("GET", base, stranger), call("GET", f"{base}/{a.run}p0/state", stranger)
    results["stranger reads the base"] = (s_base, (403, 4103) if a.hardened else (200, 403))
    results["stranger reads the cell state"] = (s_state, (403, 4103))
    bad = 0
    for name, (code, want) in results.items():
        ok = code in want
        bad += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {code} (expected {'/'.join(map(str, want))})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
