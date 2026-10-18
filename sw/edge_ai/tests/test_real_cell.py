"""Pure logic of tools/real_cell.py: backoff, retry, sweep averaging, cos^2 fit, new-reading collection."""
import math
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from real_cell import backoff_s, malus_fit, new_readings, retry, sweep_rows   # noqa: E402


def test_backoff_doubles_and_caps_like_the_firmware():
    assert [backoff_s(n) for n in range(0, 9)] == [0, 1, 2, 4, 8, 16, 32, 60, 60]


def test_retry_waits_with_backoff_until_success():
    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 4:
            raise requests.ConnectionError("down")
        return "ok"
    assert retry(flaky, "x", sleep=waits.append) == "ok"
    assert waits == [1, 2, 4]


def test_retry_gives_up_after_tries_and_never_raises():
    waits = []

    def down():
        raise RuntimeError("POST 500")
    assert retry(down, "x", tries=3, sleep=waits.append) is None
    assert waits == [1, 2]


def test_sweep_rows_average_and_ratio_to_first_point():
    rows = sweep_rows([(0, [100, 102, 98]), (45, [50, 51]), (90, [2]), (0, [99])])
    assert rows == [(0, 100.0, 1.0), (45, 50.5, 0.505), (90, 2.0, 0.02), (0, 99.0, 0.99)]


def test_malus_fit_recovers_amplitude_offset_and_leak():
    angles = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 0]
    lux = [700 * math.cos(math.radians(a - 4)) ** 2 + 12 for a in angles]
    amp, base, off, rms = malus_fit(angles, lux)
    assert abs(amp - 700) < 1 and abs(base - 12) < 1 and off == 4.0 and rms < 0.5


def test_new_readings_skips_the_old_and_repeated_cins():
    seq = iter([("a", 5.0, False), ("a", 5.0, False), ("b", 6.0, False), ("b", 6.0, False), ("c", 7.0, True)])
    vals, fake = new_readings(lambda: next(seq), 2, sleep=lambda s: None)
    assert vals == [6.0, 7.0] and fake


def test_new_readings_stops_at_timeout():
    t = iter(range(100))
    vals, _ = new_readings(lambda: ("same", 1.0, False), 3, timeout_s=5, clock=lambda: next(t), sleep=lambda s: None)
    assert vals == []
