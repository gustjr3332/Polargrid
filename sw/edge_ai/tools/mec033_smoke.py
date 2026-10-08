"""MEC033 smoke test: register the Sandbox's own MN-CSE as an IoT platform, add one device,
then read the mec:iotDev FlexContainer the Sandbox wrote into that CSE.

Usage: python tools/mec033_smoke.py <mep_base> [--keep]
  mep_base: e.g. https://try-mec.etsi.org/<sandbox-key>/mep1  (session URL, do not commit)
  Network must be 4g-5g-mc-v2x-fed-iot (mep1 runs meep-iot and the ACME MN-CSE app "mep-cse-mn", CSE_BASE_NAME "mep1-cse-mn").
  --keep: leave the platform and device registered (default deletes them at the end).

Addresses come from the Sandbox helm charts (charts/meep-acme-mn-cse, charts/meep-iot):
the iot-mgr reaches the CSE in-cluster at mep1-meep-acme-mn-cse:80, we reach it via
<mep_base>/meep-acme-mn-cse.
"""
import json
import sys
import urllib.error
import urllib.request
import uuid

PLATFORM, DEVICE = "polagrid-mn001", "cell-01"


def call(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]


def cse_get(acme, path, origin):
    return call("GET", f"{acme}/{path}", headers={
        "Accept": "application/json", "X-M2M-Origin": origin,
        "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "4"})


def main():
    base = sys.argv[1].rstrip("/")
    iot, acme = f"{base}/iots/v1", f"{base}/meep-acme-mn-cse"
    mep = base.rsplit("/", 1)[1]
    cse_rn = f"{mep}-cse-mn"  # scenario env CSE_BASE_NAME (sandbox-ctrl/v1/active), e.g. mep1-cse-mn

    print("1 CSE via ingress", *cse_get(acme, cse_rn, "CAdmin"))

    platform = {
        "iotPlatformId": PLATFORM,
        "enabled": True,
        "userTransportInfo": [{
            "id": "mqtt", "name": cse_rn, "type": "MB_TOPIC_BASED", "protocol": "MQTT", "version": "3.1.1",
            "endpoint": {"addresses": [{"host": "meep-mosquitto", "port": 1883}]},
            "security": {},
            "implSpecificInfo": {"uplinkTopics": [f"/oneM2M/req/C{PLATFORM}/{cse_rn}/json"],
                                 "downlinkTopics": [f"/oneM2M/resp/C{PLATFORM}/{cse_rn}/json"]}}],
        "customServicesTransportInfo": [{
            "id": "onem2m-http", "name": cse_rn, "type": "REST_HTTP", "protocol": "HTTP", "version": "1.1",
            "endpoint": {"addresses": [{"host": f"{mep}-meep-acme-mn-cse", "port": 80}]},
            "security": {}}],
    }
    print("2 register platform", *call("POST", f"{iot}/registered_iot_platforms", platform))

    device = {"deviceId": DEVICE, "enabled": True, "requestedIotPlatformId": PLATFORM,
              "deviceAuthenticationInfo": "none",
              "deviceMetadata": [{"key": "role", "value": "polagrid-cell"}]}
    print("3 register device", *call("POST", f"{iot}/registered_devices", device))

    origin = f"C{PLATFORM}"
    print("4 AE in CSE", *cse_get(acme, f"{cse_rn}/{PLATFORM}", origin))
    print("5 mec:iotDev in CSE", *cse_get(acme, f"{cse_rn}/{PLATFORM}/{DEVICE}", origin))

    if "--keep" not in sys.argv:
        print("6 delete device", call("DELETE", f"{iot}/registered_devices/{DEVICE}")[0])
        print("7 delete platform", call("DELETE", f"{iot}/registered_iot_platforms/{PLATFORM}")[0])


if __name__ == "__main__":
    main()
