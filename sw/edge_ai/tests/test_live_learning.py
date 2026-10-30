"""The controller keeps what it learns: AI (1) filter state across restarts, AI (3) refit from new corrections."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from live_learning import LivePreference   # noqa: E402

from polagrid import online   # noqa: E402
from polagrid.physics import KST, Room, window_lux   # noqa: E402

NOON = datetime(2026, 11, 4, 12, tzinfo=KST)


def add_rows(path, rows):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS corrections (id INTEGER PRIMARY KEY, ts TEXT, offset_lux REAL, fake INTEGER)")
    db.executemany("INSERT INTO corrections (ts, offset_lux, fake) VALUES (?,?,?)", rows)
    db.commit()
    db.close()


def test_filter_state_survives_a_restart(tmp_path):
    kf = online.ContributionFilter(2, 3)
    kf.update(np.ones((2, 3)) * 500, np.array([1.0, 0.5, 0.2]), np.array([900.0, 700.0]))
    kf.save(tmp_path / "f.npz")
    again = online.ContributionFilter(2, 3)
    assert again.load(tmp_path / "f.npz") and np.allclose(again.delta, kf.delta) and np.allclose(again.p, kf.p)
    assert not online.ContributionFilter(2, 4).load(tmp_path / "f.npz")        # other room size: start fresh
    assert not online.ContributionFilter(2, 3).load(tmp_path / "missing.npz")


def test_preference_needs_rows_then_follows_new_ones(tmp_path):
    db, pref = tmp_path / "c.db", None
    add_rows(db, [("2026-11-04T14:00:00+09:00", -300, 0), ("2026-11-04T14:30:00+09:00", -300, 0)])
    pref = LivePreference(db, tmp_path / "m.joblib")
    assert pref.offset(NOON) == 0.0 and pref.model is None                       # 2 rows: not enough
    add_rows(db, [("2026-11-04T15:00:00+09:00", -300, 0), ("2026-11-04T13:00:00+09:00", -300, 1)])
    assert pref.offset(NOON) < -100 and pref.rows == 3                           # fake row not counted
    first = pref.offset(NOON)
    add_rows(db, [("2026-11-04T12:00:00+09:00", -600, 0)])
    assert pref.offset(NOON) < first and pref.rows == 4                          # the new press moved the answer
    assert LivePreference(db, tmp_path / "m.joblib").model is not None            # restart: model loaded from file


def test_negative_offset_closes_the_cell_more():
    room = Room(rows=1, cols=1, cell_w=0.15, cell_h=0.15, desks=[(0.0, 0.6, 0.4, 0.3, 0.75)])
    ctx = {"t": NOON, "outdoor": window_lux(room, NOON), "angles": np.array([0.0]), "desk_lux": np.array([800.0])}
    default = online.polagrid_online(room)(dict(ctx))
    darker = online.polagrid_online(room, glare_offset=lambda c: -1000.0)(dict(ctx))
    assert default[0] == 0 and darker[0] > 30     # 800 lux is fine by default, too bright for this user


def test_web_source_reads_the_page_model(tmp_path, monkeypatch):
    import json
    import live_learning
    monkeypatch.setattr(live_learning, "ROOT", tmp_path)
    pref = LivePreference(tmp_path / "none.db", source="web")
    assert pref.offset(NOON) == 0.0 and pref.model is None                       # the page has posted nothing yet
    p = {"mean": [12, 0, 0, 30, 180, 20000], "scale": [2, 1, 1, 10, 30, 5000], "coef": [0, 0, 0, 0, 0, 0], "intercept": -250, "n": 4}
    live_learning.save_params(p)
    assert pref.offset(NOON) == -250 and pref.rows == 4
    live_learning.save_params({**p, "intercept": -400, "n": 5})
    assert pref.offset(NOON) == -400 and pref.rows == 5                          # the page posted again: picked up
    live_learning.save_params({**p, "intercept": -5000})
    assert pref.offset(NOON) == -1000.0                                          # clipped like the server fit
