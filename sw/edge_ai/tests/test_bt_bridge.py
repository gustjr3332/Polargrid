"""tools/bt_bridge.py against a fake serial port and a fake CSE: command -> BT lines, BT lines -> CSE requests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from bt_bridge import Bridge   # noqa: E402


class FakeSerial:
    def __init__(self):
        self.out, self.rx = [], b""

    def write(self, data):
        self.out.append(data.decode())

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n):
        data, self.rx = self.rx[:n], self.rx[n:]
        return data


class Reply:
    def __init__(self, code, body=None):
        self.status_code, self.body = code, body

    def json(self):
        return self.body


class FakeCse:
    host, cse = "http://x", "mn"

    def __init__(self):
        self.replies, self.sent = [], []

    def _session(self):
        return self

    def get(self, url, headers, timeout):
        return self.replies.pop(0)

    def put(self, path, origin, body):
        self.sent.append(("PUT", path, origin, body))

    def create(self, path, origin, content):
        self.sent.append(("CIN", path, origin, content))


def command(cmd, angle, **extra):
    return Reply(200, {"m2m:cin": {"con": json.dumps({"cmd": cmd, "angles": [angle], **extra})}})


def test_commands_go_out_as_cell_lines_and_cell_lines_reach_the_cse():
    c, ser = FakeCse(), FakeSerial()
    b = Bridge(c, "real1", 0)
    b.ser = ser
    c.replies = [command("old", 30), command("c1", 45), command("c1", 45), command("c2", float("nan")),
                 command("c3", 10, mode="privacy"), Reply(403)]
    assert b.poll(0) and ser.out == ["PING\n"]                      # first command after start is old: skipped
    ser.out.clear()
    assert b.poll(2) and ser.out == ["PING\n", "PRIV 0\n", "A 0 45.0\n"]
    ser.out.clear()
    assert b.poll(4) and ser.out == ["PING\n"]                      # same id again: nothing
    ser.rx = b"OK 0 45.0 3550\r\nPOS 45"                            # a line split across two reads
    assert b.lines() == ["OK 0 45.0 3550"]
    ser.rx = b".0\nDESK 120.5\nLUX 300.0 -1.0\n"
    for text in b.lines():
        b.line(text, 10)
    assert c.sent == [("PUT", "real1p0/state", "Creal1p0", {"cod:opeLl": {"opeLl": 50}}),
                      ("CIN", "real1env/desks", "Creal1env", {"cmd": "c1", "lux": [120.5]}),
                      ("CIN", "real1p0/lux", "Creal1p0", {"lux": 300.0})]  # desk -1 = sensor missing: no reading
    b.published = None                                              # a new setup: state is PUT again unasked
    b.publish()
    assert c.sent[-1][0] == "PUT" and b.published == 50
    ser.out.clear()
    assert b.poll(20) and ser.out == ["PING\n", "FAILSAFE\n"]       # nonsense angle: the cell opens
    ser.out.clear()
    assert b.poll(22) and ser.out == ["PING\n", "PRIV 1\n", "A 0 90.0\n"]
    b.line("DESK 99.0", 22 + 26)                                   # too late: answers nothing
    assert c.sent[-1][0] == "PUT" and b.pending is None
    assert not b.poll(30)                                           # 403: provision again


def test_lost_port_drops_lines_until_reopened():
    class Broken(FakeSerial):
        def write(self, data):
            raise OSError("gone")

        def close(self):
            pass

    b = Bridge(FakeCse(), "real1", 0)
    b.ser = Broken()
    b.send("PING")
    assert b.ser is None and b.lines() == []
    b.send("PING")                                                  # no port: dropped, no error
