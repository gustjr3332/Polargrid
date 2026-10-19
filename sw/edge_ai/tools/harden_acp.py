"""Narrow the MN's defaultACP: replace the wildcard rule {"acor": ["/*"], "acop": 63} with the IN CSE and the IN-forwarded admin.

tinyIoT builds defaultACP with ALLOWED_REMOTE_CSE_ID as the originator list. Our MNs run with "/*", so every originator that
reaches the MN through the IN (a CSE-ID-qualified originator such as /tinyiot/Cwhoever) gets full rights (acop 63) on the
CSE base and on every resource that has no ACP of its own. This keeps access for the IN itself (/tinyiot) and the admin
forwarded by the IN (/tinyiot/CAdmin, used to create the zone ACPs through the IN). The other rules stay: "all" may create
(AE registration, as oneM2M requires), C*ctl / C*view may discover. Roles on cells and containers come from their own ACPs
(zone.py), which this does not touch. Idempotent. Run it after the MN is up, as CAdmin, directly on the MN:

    python3 tools/harden_acp.py --host http://127.0.0.1:3001 --cse TinyIoT-mn001           # change
    python3 tools/harden_acp.py --host http://127.0.0.1:3001 --cse TinyIoT-mn001 --check   # only probe, change nothing
    python3 tools/harden_acp.py --mns 10                                                  # MN 1..10 on ports 3001..3010

The MN keeps the change in its database, so it survives a restart; a fresh database (tools/fresh_mn.sh) needs it again.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid.onem2m import Client, _headers   # noqa: E402
from polagrid.zone import ADMIN, IN_CSI          # noqa: E402

WILDCARD = {"acor": ["/*"], "acop": 63}


def narrowed(acr, in_csi=IN_CSI):
    """The rule list with the wildcard replaced; the same list if there is no wildcard rule."""
    out = []
    for r in acr:
        if r.get("acor") == WILDCARD["acor"]:
            out.append({"acor": [in_csi, f"{in_csi}/{ADMIN}"], "acop": r["acop"]})
        else:
            out.append(r)
    return out


def probe(c, origin):
    """Status codes of two requests as `origin`: read the CSE base, discover containers under it."""
    s = c._session()
    base = f"{c.host}/{c.cse}"
    return (s.get(base, headers=_headers(origin), timeout=10).status_code,
            s.get(f"{base}?fu=1&ty=3", headers=_headers(origin), timeout=10).status_code)


def harden(c, check=False):
    path = f"{c.host}/{c.cse}/defaultACP"
    acp = c._session().get(path, headers=_headers(ADMIN), timeout=30).json()["m2m:acp"]
    acr = acp["pv"]["acr"]
    new = narrowed(acr)
    wild = any(r.get("acor") == WILDCARD["acor"] for r in acr)
    print(f"[{c.cse}] defaultACP rules: {len(acr)}, wildcard {'present' if wild else 'already gone'}")
    stranger = f"{IN_CSI}/Cstranger"
    print(f"[{c.cse}] a stranger {stranger} (read base, discover): {probe(c, stranger)}")
    if check or not wild:
        return not wild
    c.put("defaultACP", ADMIN, {"m2m:acp": {"pv": {"acr": new}}})
    print(f"[{c.cse}] after: {probe(c, stranger)}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="http://127.0.0.1:3001")
    ap.add_argument("--cse", default="TinyIoT-mn001")
    ap.add_argument("--mns", type=int, help="MN 1..N on ports 3001.. (overrides --host/--cse)")
    ap.add_argument("--check", action="store_true", help="probe only, change nothing")
    a = ap.parse_args()
    targets = [(f"http://127.0.0.1:{3000 + k}", f"TinyIoT-mn{k:03d}") for k in range(1, a.mns + 1)] if a.mns else [(a.host, a.cse)]
    ok = all([harden(Client(h, n), a.check) for h, n in targets])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
