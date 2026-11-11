"""MqttSession of tools/fake_cell.py against a fake broker (no paho, no network): primitives out, responses and notifications in."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from fake_cell import MqttSession, subscribe   # noqa: E402
from polagrid.onem2m import Client, _headers   # noqa: E402

HOST, CSE, RI = "http://127.0.0.1:3001", "TinyIoT-mn001", "id-mn001"


def make(reply):
    """Session whose 'broker' answers each published primitive with reply(primitive) -> response dict, or None for silence."""
    sent = []

    def publish(topic, payload):
        prim = json.loads(payload)
        sent.append((topic, prim))
        r = reply(prim)
        if r is not None:
            s.feed(f"/oneM2M/resp/{prim['fr']}/{RI}/json", json.dumps(r))
    s = MqttSession(HOST, CSE, RI, publish)
    return s, sent


def test_get_la_is_a_retrieve_primitive_and_json_gives_the_pc():
    s, sent = make(lambda p: {"rsc": 2000, "rqi": p["rqi"], "pc": {"m2m:cin": {"con": "{}"}}})
    r = s.get(f"{HOST}/{CSE}/real1p0/command/la", headers=_headers("Creal1p0"), timeout=1)
    topic, prim = sent[0]
    assert topic == f"/oneM2M/req/Creal1p0/{RI}/json"
    assert prim["op"] == 2 and prim["to"] == f"{CSE}/real1p0/command/la" and prim["fr"] == "Creal1p0" and prim["rvi"] == "3"
    assert "ty" not in prim and "pc" not in prim
    assert r.status_code == 200 and r.json() == {"m2m:cin": {"con": "{}"}}


def test_client_post_creates_with_ty_and_pc_and_409_means_exist_ok():
    s, sent = make(lambda p: {"rsc": 4105, "rqi": p["rqi"]})
    from polagrid import onem2m
    onem2m._local.s = s
    try:
        assert Client(HOST, CSE).post("real1env", "Creal1env", {"m2m:cnt": {"rn": "sun"}}, 3, exist_ok=True) is None
        prim = sent[0][1]
        assert prim["op"] == 1 and prim["ty"] == 3 and prim["pc"] == {"m2m:cnt": {"rn": "sun"}} and prim["to"] == f"{CSE}/real1env"
    finally:
        del onem2m._local.s


def test_rsc_table_and_unknown_is_500():
    for rsc, code in [(2000, 200), (2004, 200), (2001, 201), (4004, 404), (4103, 403), (4105, 409), (5000, 500), (4000, 500)]:
        s, _ = make(lambda p, rsc=rsc: {"rsc": rsc, "rqi": p["rqi"]})
        assert s.put(f"{HOST}/{CSE}/x", headers=_headers("Cx"), data="{}", timeout=1).status_code == code


def test_late_or_foreign_response_is_dropped_and_silence_times_out():
    s, _ = make(lambda p: {"rsc": 2000, "rqi": "someone-else"})
    with pytest.raises(TimeoutError):
        s.get(f"{HOST}/{CSE}/x", headers=_headers("Cx"), timeout=0.2)
    s.feed(f"/oneM2M/resp/Cx/{RI}/json", json.dumps({"rsc": 2000, "rqi": "late"}))   # nobody waits: ignored, no crash


def test_notification_with_a_cin_is_queued_and_verification_is_not():
    s, _ = make(lambda p: None)
    s.feed(f"/oneM2M/req/{RI}/Creal1p0/json", json.dumps({"m2m:sgn": {"vrq": True, "sur": "/s"}}))
    assert s.notified.empty()
    s.feed(f"/oneM2M/req/{RI}/Creal1p0/json", "not json")
    assert s.notified.empty()
    s.feed(f"/oneM2M/req/{RI}/Creal1p0/json", json.dumps({"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": "{}"}}, "net": 3}}}))
    assert not s.notified.empty()


def test_notification_for_another_cell_or_run_is_ignored():
    s = MqttSession(HOST, CSE, RI, lambda t, p: None, "Creal1p0")
    nev = json.dumps({"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": "{}"}}, "net": 3}}})
    s.feed(f"/oneM2M/req/{RI}/Creal2p0/json", nev)
    s.feed(f"/oneM2M/req/{RI}/Creal1p1/json", nev)
    assert s.notified.empty()
    s.feed(f"/oneM2M/req/{RI}/Creal1p0/json", nev)
    assert not s.notified.empty()


def test_subscribe_posts_a_sub_with_our_nu_and_updates_nu_on_409():
    codes = iter([4105, 2004])
    s, sent = make(lambda p: {"rsc": next(codes), "rqi": p["rqi"]})
    from polagrid import onem2m
    onem2m._local.s = s
    nu = "mqtt://127.0.0.1:1883/Creal1p0/json"
    try:
        subscribe(Client(HOST, CSE), "real1", 0, nu)
    finally:
        del onem2m._local.s
    assert sent[0][1]["op"] == 1 and sent[0][1]["ty"] == 23 and sent[0][1]["pc"]["m2m:sub"]["nu"] == [nu]
    assert sent[1][1]["op"] == 3 and sent[1][1]["to"] == f"{CSE}/real1p0/command/s" and sent[1][1]["pc"] == {"m2m:sub": {"nu": [nu]}}
