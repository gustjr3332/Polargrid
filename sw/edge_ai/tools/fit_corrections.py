"""Fit the AI (3) preference model (ai.fit_preference) from the app's saved corrections.

The Comfort screen of the phone mockup saves every "Too bright" / "Too dark" press in sw/app_ui/demo/corrections.db
(see sw/app_ui/README.md). This reads those rows, rebuilds the model input ai.features() from each row's timestamp and
fits Ridge on the wanted offset (negative = too bright). Rows from tools/fake_cell.py (fake = 1) are skipped unless
--include-fake, because they are not a person's preference.

    python3 tools/fit_corrections.py                       # real rows only, needs 3 or more
    python3 tools/fit_corrections.py --include-fake        # to try the chain with fake-cell rows (the model file is marked FAKE)

The sun position comes from the timestamp, the outdoor light is the clear-sky model value (cloud 0): the real cell has no
outdoor sensor yet. So the model learns "hour and season" much more than weather.
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import joblib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid import ai                                     # noqa: E402
from polagrid.physics import Room, sun_position, window_lux   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT.parent / "app_ui" / "demo" / "corrections.db"
MIN_ROWS = 3   # as in polagrid/prefs.py


def moment_features(ts, room=None):
    """ai.features() for the ISO time string ts (the app stores KST with an offset)."""
    room, t = room or Room(), datetime.fromisoformat(ts)
    alt, az = sun_position(t, room.lat, room.lon)
    return ai.features(t, alt, az, window_lux(room, t, 0.0))


def load_corrections(db_path, include_fake=False):
    """([features], [wanted offset lux], rows skipped as fake) from corrections.db."""
    db = sqlite3.connect(db_path)
    try:
        rows = db.execute("SELECT ts, offset_lux, fake FROM corrections ORDER BY id").fetchall()
    finally:
        db.close()
    used = [(ts, off) for ts, off, fake in rows if include_fake or not fake]
    return [moment_features(ts) for ts, _ in used], [off for _, off in used], len(rows) - len(used)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--include-fake", action="store_true")
    ap.add_argument("--out", help="model file (default models/preference_real.joblib, preference_FAKE.joblib with --include-fake)")
    a = ap.parse_args()
    if not Path(a.db).exists():
        sys.exit(f"no corrections database at {a.db}: press a button on the Comfort screen first")
    x, y, skipped = load_corrections(a.db, a.include_fake)
    print(f"{len(y)} corrections used, {skipped} fake-cell rows skipped")
    if len(y) < MIN_ROWS:
        sys.exit(f"need {MIN_ROWS} or more corrections to fit (the AI needs a few presses before it can guess)")
    model = ai.fit_preference(x, y)
    out = Path(a.out) if a.out else ROOT / "models" / ("preference_FAKE.joblib" if a.include_fake else "preference_real.joblib")
    out.parent.mkdir(exist_ok=True)
    joblib.dump(model, out)
    now = moment_features(datetime.now().astimezone().isoformat())
    print(f"wrote {out}{'  (FAKE rows included, not a real preference)' if a.include_fake else ''}")
    print(f"offsets in data: min {min(y):.0f}, mean {sum(y) / len(y):.0f}, max {max(y):.0f} lux; model now: {float(model.predict([now])[0]):+.0f} lux")


if __name__ == "__main__":
    main()
