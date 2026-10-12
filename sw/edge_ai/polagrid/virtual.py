"""Pre-train AI (3) on virtual days, save the model, and check how it holds up when the real room differs.

The virtual days come from physics.py, so the model learns the physics model's assumptions. It is a warm start for
the real window (use it until real data arrives, then retrain), not a measured result.
Domain randomization: every training day uses a slightly different room (window direction, desk positions), a random
cloud level and a noisy outdoor-light feature, so the model does not depend on one exact geometry.

    python -m polagrid.virtual train --rows 3 --cols 4 --days 120 --jitter     # writes models/predictor_3x4.joblib
    python -m polagrid.virtual robust --rows 3 --cols 4 --days 60              # nominal vs randomized training
"""
import argparse
import dataclasses
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np

from . import ai, evaluate
from .physics import DESK_MIN_LUX, KST, Room, simulate, sun_position

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
AZIMUTH_JITTER_DEG, DESK_JITTER_M, OUTDOOR_NOISE = 10.0, 0.25, 0.05


def model_path(room):
    return MODEL_DIR / f"predictor_{room.rows}x{room.cols}.joblib"


def jitter_room(room, rng, az_deg=AZIMUTH_JITTER_DEG, desk_m=DESK_JITTER_M):
    """A room like `room` but with the window turned a few degrees and the desks nudged."""
    desks = [(x + rng.uniform(-desk_m, desk_m), max(0.5, y + rng.uniform(-desk_m, desk_m)), w, d, h)
             for x, y, w, d, h in room.desks]
    return dataclasses.replace(room, window_azimuth=room.window_azimuth + rng.uniform(-az_deg, az_deg), desks=desks)


def training_set(room, n_days, jitter=True, seed=1):
    """(features, angles) rows from n_days virtual days spread over the year, decided by AI (2) with exact contributions."""
    rng = np.random.default_rng(seed)
    if jitter:
        picks = [(date(2026, 1, 1) + timedelta(days=int(d)), float(rng.uniform(0, 0.9)))
                 for d in rng.choice(365, n_days, replace=n_days > 365)]
    else:
        # evenly over the year (evaluate.days with a 365 // n stride would cover only part of the year above 183 days)
        picks = [(date(2026, 1, 1) + timedelta(days=int(i * 365 / n_days)), float(rng.choice([0.0, 0.0, 0.3, 0.7])))
                 for i in range(n_days)]
    x, angles = [], []
    for day, cloud in picks:
        for xi, ai_ in evaluate.teacher_log(jitter_room(room, rng) if jitter else room, day, cloud):
            x.append(xi)
            angles.append(ai_)
    x = np.array(x)
    if jitter:
        x[:, 5] *= 1 + rng.normal(0, OUTDOOR_NOISE, len(x))
    return x, np.array(angles)


def train(room, n_days, jitter=True, seed=1):
    x, angles = training_set(room, n_days, jitter, seed)
    return ai.fit_predictor(x, angles)


def save(model, room, n_days, jitter, path=None):
    path = Path(path or model_path(room))
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "rows": room.rows, "cols": room.cols, "days": n_days, "jitter": jitter}, path)
    return path


def load(room, path=None):
    """Load a saved predictor; the saved cell grid must match the room."""
    blob = joblib.load(path or model_path(room))
    if (blob["rows"], blob["cols"]) != (room.rows, room.cols):
        raise ValueError(f"model is for {blob['rows']}x{blob['cols']} cells, room has {room.rows}x{room.cols}")
    return blob["model"]


def score(model, room, test_days):
    """Per-day average glare / under-lit hours (desk-hours) of the predictor on `room`, with 5-degree hysteresis.

    Same metrics as evaluate.run_day without sensor noise, but all steps of a day are predicted in one call.
    """
    glare_h = dark_h = 0.0
    for day, cloud in test_days:
        log = evaluate.teacher_log(room, day, cloud)       # only for the features of this room's day
        pred = ai.to_angles(np.clip(model.predict(np.array([x for x, _ in log])), ai.T_MIN, ai.T_MAX))
        cur = np.zeros(room.n_cells)
        t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
        for new in pred:
            cur = np.where(np.abs(new - cur) < 5, cur, new)
            truth = simulate(room, t, cur, cloud)
            glare_h += evaluate.STEP_MIN / 60 * np.sum(truth["glare"] > 0)
            if sun_position(t, room.lat, room.lon)[0] > 0:
                dark_h += evaluate.STEP_MIN / 60 * np.sum(truth["desk_lux"] < DESK_MIN_LUX)
            t += timedelta(minutes=evaluate.STEP_MIN)
    return glare_h / len(test_days), dark_h / len(test_days)


def real_like_rooms(room):
    """Rooms that differ from the training room the way a real installation will: window turned, desks moved."""
    turned = dataclasses.replace(room, window_azimuth=room.window_azimuth + 8)
    moved = dataclasses.replace(room, desks=[(x + 0.2, y - 0.2, w, d, h) for x, y, w, d, h in room.desks])
    both = dataclasses.replace(turned, desks=moved.desks)
    return {"as designed": room, "window +8 deg": turned, "desks moved 0.2 m": moved, "both": both}


def robust(room, n_days):
    test = evaluate.days(date(2026, 1, 4), 12, 30, seed=2)
    models = {"nominal training": train(room, n_days, jitter=False), "randomized training": train(room, n_days, jitter=True)}
    print(f"{room.rows}x{room.cols} cells, {n_days} training days, 12 test days; glare h / under-lit h per day (desk-hours)")
    print(f"{'test room':<22}" + "".join(f"{k:>24}" for k in models))
    for name, r in real_like_rooms(room).items():
        cells = [score(m, r, test) for m in models.values()]
        print(f"{name:<22}" + "".join(f"{g:>14.2f} / {d:<7.2f}" for g, d in cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "robust"])
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--jitter", action="store_true", help="domain randomization (train only; robust compares both)")
    ap.add_argument("--out", help="model file (default models/predictor_<rows>x<cols>.joblib)")
    a = ap.parse_args()
    room = Room(rows=a.rows, cols=a.cols)
    if a.cmd == "robust":
        return robust(room, a.days)
    path = save(train(room, a.days, a.jitter), room, a.days, a.jitter, a.out)
    print(f"saved {path} ({a.days} days, jitter={a.jitter})")


if __name__ == "__main__":
    main()
