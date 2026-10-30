"""AI (3) while the system runs: refit the preference model whenever the app has saved a new correction.

fit_corrections.py does the same by hand once. LivePreference is called by the controller every step: when
corrections.db has a different number of usable rows than at the last fit (and at least MIN_ROWS), it refits Ridge,
saves the model, and the next decision aims below a lower or higher desk lux. The model file is loaded at start, so a
restart keeps what was learned. Before there are enough rows (and without a saved model) the offset is 0.

source="web": the model is not fitted here but read from models/web_params.json, which the phone page (app_ui/mockup,
browser-side Ridge) posts to the demo server after each new correction. Same linear model, learned in the browser.

The offset is read for the time given by the caller. The app stamps corrections with the wall clock, so the real-cell
loop (which runs a simulated sun) passes the wall clock too, not the simulated time.
"""
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fit_corrections import DEFAULT_DB, MIN_ROWS, ROOT, load_corrections, moment_features   # noqa: E402

sys.path.insert(0, str(ROOT))
from polagrid import ai   # noqa: E402
from polagrid.physics import KST   # noqa: E402

OFFSET_LIMIT_LUX = 1000.0   # as prefs.run_day: one bad fit must not move the target by more than this


def web_params_path(include_fake=False):
    return ROOT / "models" / ("web_params_FAKE.json" if include_fake else "web_params.json")


def learn_payload(db_path=DEFAULT_DB, include_fake=False, now=None):
    """What the phone page learns from: model input x and wanted offset y of every usable correction, the input for now
    and for each hour 7..19 of today (the page draws the offset curve with them). Features stay in Python (sun position)."""
    now = now or datetime.now(KST)
    try:
        x, y, _ = load_corrections(db_path, include_fake)
    except sqlite3.OperationalError:   # no corrections table yet: nothing pressed
        x, y = [], []
    day = now.replace(minute=0, second=0, microsecond=0)
    return {"x": x, "y": y, "now": moment_features(now.isoformat()),
            "hours": [moment_features(day.replace(hour=h).isoformat()) for h in range(7, 20)]}


def save_params(body, include_fake=False):
    """Validate the browser's model (mean, scale, coef: 6 numbers each, intercept, n) and write it for source="web"."""
    p = {k: [float(v) for v in body[k]] for k in ("mean", "scale", "coef")}
    p["intercept"], p["n"] = float(body["intercept"]), int(body["n"])
    flat = p["mean"] + p["scale"] + p["coef"] + [p["intercept"]]
    if any(len(p[k]) != 6 for k in ("mean", "scale", "coef")) or min(p["scale"]) <= 0 or p["n"] < MIN_ROWS             or not all(math.isfinite(v) for v in flat):
        raise ValueError("need mean, scale, coef (6 finite numbers each, scale > 0), intercept, n >= %d" % MIN_ROWS)
    path = web_params_path(include_fake)
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(p))
    tmp.replace(path)
    return path


class LinearModel:
    """The browser's Ridge: standardise with mean/scale, then dot with coef (same maths as the sklearn pipeline)."""

    def __init__(self, p):
        self.p = p

    def predict(self, x, zmax=3.0):
        """zmax: inputs further than this many standard deviations from the corrections are held there (see ridge.js)."""
        z = np.clip((np.asarray(x, float) - self.p["mean"]) / self.p["scale"], -zmax, zmax)
        return z @ np.asarray(self.p["coef"]) + self.p["intercept"]


class LivePreference:
    def __init__(self, db_path=DEFAULT_DB, model_path=None, include_fake=False, source="server"):
        self.db, self.include_fake, self.source, self.mtime = Path(db_path), include_fake, source, None
        self.path = Path(model_path) if model_path else ROOT / "models" / (
            "preference_FAKE.joblib" if include_fake else "preference_real.joblib")
        self.rows, self.model = -1, None
        if source == "server" and self.path.exists():
            self.model = joblib.load(self.path)

    def refit(self):
        """True when a new model was fitted (source "web": read) from the current rows."""
        if self.source == "web":
            path = web_params_path(self.include_fake)
            if not path.exists() or path.stat().st_mtime_ns == self.mtime:
                return False
            p = json.loads(path.read_text())
            self.model, self.rows, self.mtime = LinearModel(p), p["n"], path.stat().st_mtime_ns
            return True
        if not self.db.exists():
            return False
        x, y, _ = load_corrections(self.db, self.include_fake)
        if len(y) == self.rows or len(y) < MIN_ROWS:
            return False
        self.model, self.rows = ai.fit_preference(x, y), len(y)
        self.path.parent.mkdir(exist_ok=True)
        joblib.dump(self.model, self.path)
        return True

    def offset(self, t):
        """Lux to add to the default glare limit at time t (a datetime with a zone)."""
        self.refit()
        if self.model is None:
            return 0.0
        pred = float(self.model.predict([moment_features(t.isoformat())])[0])
        return float(np.clip(pred, -OFFSET_LIMIT_LUX, OFFSET_LIMIT_LUX))
