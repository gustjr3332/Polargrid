"""MEC011 smoke test against an ETSI MEC Sandbox MEP.

Usage: python tools/mec011_smoke.py <mep_base> <app_instance_id> [cse_url]
  mep_base: e.g. https://try-mec.etsi.org/<sandbox-key>/mep1  (session URL, do not commit)
  app_instance_id: created in the Sandbox UI (MEC App. Instance IDs > NEW)
"""
import json
import sys
import urllib.request


def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def main():
    base, app_id = sys.argv[1].rstrip("/"), sys.argv[2]
    cse = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:3000/TinyIoT"
    app = f"{base}/mec_app_support/v2/applications/{app_id}"
    svc = f"{base}/mec_service_mgmt/v1"

    print("confirm_ready", call("POST", f"{app}/confirm_ready", {"indication": "READY"})[0])

    ser = {
        "serName": "polagrid-daylight",
        "serCategory": {"href": "catalogue/polagrid", "id": "polagrid", "name": "PolaGrid", "version": "v1"},
        "version": "1.0",
        "state": "ACTIVE",
        "transportInfo": {
            "id": "polagrid-onem2m-http",
            "name": "oneM2M HTTP binding of the zone MN-CSE",
            "type": "REST_HTTP",
            "protocol": "HTTP",
            "version": "1.1",
            "endpoint": {"uris": [cse]},
            "security": {},
        },
        "serializer": "JSON",
        "scopeOfLocality": "MEC_HOST",
        "consumedLocalOnly": True,
        "isLocal": True,
    }
    st, created = call("POST", f"{app}/services".replace("mec_app_support/v2", "mec_service_mgmt/v1"), ser)
    print("register", st, created.get("serInstanceId"))

    st, found = call("GET", f"{svc}/services?ser_name=polagrid-daylight")
    eps = [s["transportInfo"]["endpoint"]["uris"] for s in found]
    print("discover", st, eps)
    assert eps and eps[0] == [cse], "registered endpoint not discoverable"


if __name__ == "__main__":
    main()
