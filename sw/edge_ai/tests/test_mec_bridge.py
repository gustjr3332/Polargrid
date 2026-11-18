"""tools/mec_bridge.py: MEC 011 answers become content instances, and the session URL stays out of them."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from mec_bridge import SERVICES, TIME, changes, read, service_rows, step   # noqa: E402

BASE = "https://sandbox.example/sbxSECRET/mep1"
MEC = {
    SERVICES: [
        {"serName": "mec033-1", "serInstanceId": "b", "state": "ACTIVE", "version": "3.1.1",
         "transportInfo": {"endpoint": {"uris": [f"{BASE}/iots/v1/"]}}},
        {"serName": "mec013-1", "serInstanceId": "a", "state": "INACTIVE", "version": "3.1.1", "transportInfo": {}},
    ],
    TIME: {"seconds": 1794458917, "nanoSeconds": 0, "timeSourceStatus": "TRACEABLE"},
}


class FakeCse:
    def __init__(self):
        self.cins = []

    def create(self, path, origin, content):
        self.cins.append((path, origin, content))

    def discover(self, origin, lbl, ty):
        return [f"TinyIoT-mn001/r1mec/{lbl.rsplit('/', 1)[1]}"]

    def latest(self, path, origin):
        return next(c for p, _, c in reversed(self.cins) if p == path)


def test_rows_are_sorted_and_carry_no_session_key():
    rows = service_rows(MEC[SERVICES], BASE)
    assert [r["name"] for r in rows] == ["mec013-1", "mec033-1"]
    assert rows[1] == {"name": "mec033-1", "id": "b", "state": "ACTIVE", "version": "3.1.1", "paths": ["/iots/v1/"]}
    assert rows[0]["paths"] == [] and "sbxSECRET" not in str(rows)


def test_services_are_written_on_change_and_time_every_poll():
    c = FakeCse()
    rows = step(c, "r1", MEC.__getitem__, None, BASE)
    rows = step(c, "r1", MEC.__getitem__, rows, BASE)
    assert [p for p, _, _ in c.cins] == ["r1mec/services", "r1mec/time", "r1mec/time"]
    assert all(o == "Cr1mec" for _, o, _ in c.cins)
    changed = {**MEC, SERVICES: MEC[SERVICES][:1]}
    step(c, "r1", changed.__getitem__, rows, BASE)
    assert c.cins[-2][0] == "r1mec/services" and len(c.cins[-2][2]["services"]) == 1


def test_a_consumer_reads_both_through_the_cse():
    c = FakeCse()
    step(c, "r1", MEC.__getitem__, None, BASE)
    got = read(c, "r1")
    assert got["time"] == {"seconds": 1794458917, "nanoSeconds": 0, "status": "TRACEABLE"}
    assert [s["state"] for s in got["services"]["services"]] == ["INACTIVE", "ACTIVE"]


def test_changes_name_added_removed_and_state_changes_only():
    old = {"mec013-1": "ACTIVE", "mec033-1": "ACTIVE", "mec046-1": "ACTIVE"}
    new = {"mec013-1": "ACTIVE", "mec033-1": "INACTIVE", "mec021-1": "ACTIVE"}
    assert changes(old, new) == ["mec021-1: new -> ACTIVE", "mec033-1: ACTIVE -> INACTIVE", "mec046-1: ACTIVE -> gone"]
    assert changes(old, dict(old)) == []
