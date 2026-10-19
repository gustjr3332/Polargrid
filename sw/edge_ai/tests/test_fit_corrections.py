"""tools/fit_corrections.py: corrections.db rows -> preference model input."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from fit_corrections import load_corrections, moment_features   # noqa: E402


def make_db(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE corrections (id INTEGER PRIMARY KEY, ts TEXT, offset_lux REAL, fake INTEGER)")
    db.executemany("INSERT INTO corrections (ts, offset_lux, fake) VALUES (?,?,?)", [
        ("2026-11-04T14:05:00+09:00", -200, 0), ("2026-11-04T11:40:00+09:00", 100, 0), ("2026-11-04T15:00:00+09:00", -300, 1)])
    db.commit()
    db.close()


def test_fake_rows_are_skipped_unless_asked(tmp_path):
    make_db(tmp_path / "c.db")
    x, y, skipped = load_corrections(tmp_path / "c.db")
    assert (len(x), y, skipped) == (2, [-200, 100], 1)
    assert len(load_corrections(tmp_path / "c.db", include_fake=True)[0]) == 3


def test_features_follow_the_time_of_day():
    noon, night = moment_features("2026-11-04T12:00:00+09:00"), moment_features("2026-11-04T23:00:00+09:00")
    assert noon[0] == 12 and noon[3] > 20 and noon[5] > 1000    # hour, sun altitude, outdoor lux
    assert night[3] < 0 and night[5] < 100
