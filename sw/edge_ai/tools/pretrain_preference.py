"""AI (3) start model for the real cell: what two virtual users taught the preference model.

polagrid/prefs.py has virtual users who press "too bright" once per too-bright episode and log the lux offset they wanted
("light sensitive": -300 lux all day, "afternoon sensitive": 0 at 07:00 falling to -400 at 19:00). This runs both over 40
virtual days and saves every logged correction (model input, wanted offset) to models/preference_pretrained.json.
tools/live_learning.py LivePreference loads it at start and refits it together with the real presses of the app.
Virtual users are not a person's preference: it is a start value that the first real presses override.

    python3 tools/pretrain_preference.py
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid import ai, evaluate, prefs   # noqa: E402
from polagrid.physics import Room   # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "models" / "preference_pretrained.json"
DAYS = 40


def collect(room, offset_fn, use_days):
    """Corrections of one virtual user over the days; the model refits daily as in prefs.trial, so later days see its limit."""
    xs, ys, model = [], [], None
    for day, cloud in use_days:
        samples = prefs.run_day(room, day, cloud, offset_fn, model)[3]
        xs += [[float(v) for v in x] for x, _ in samples]
        ys += [float(y) for _, y in samples]
        if len(xs) >= 3:
            model = ai.fit_preference(xs, ys)
    return xs, ys


def main():
    room, use = Room(), evaluate.days(date(2026, 3, 1), DAYS, 5, seed=3)
    x, y = [], []
    for name, fn in prefs.USERS.items():
        ux, uy = collect(room, fn, use)
        print(f"{name}: {len(uy)} corrections, mean wanted offset {sum(uy) / max(1, len(uy)):.0f} lux")
        x += ux
        y += uy
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"x": x, "y": y, "users": list(prefs.USERS), "days": DAYS}))
    print(f"wrote {OUT} ({len(y)} rows)")


if __name__ == "__main__":
    main()
