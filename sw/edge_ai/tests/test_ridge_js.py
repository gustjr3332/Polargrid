"""app_ui/mockup/ridge.js (the phone page's learning) gives the same model as ai.fit_preference."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from fit_corrections import moment_features   # noqa: E402
from live_learning import LinearModel, learn_payload, save_params   # noqa: E402

from polagrid import ai   # noqa: E402

RIDGE_JS = Path(__file__).resolve().parents[2] / "app_ui" / "mockup" / "ridge.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

JS = "const r=require(process.argv[1]);const c=JSON.parse(require('fs').readFileSync(0,'utf8'));" \
     "const p=r.fitRidge(c.x,c.y);console.log(JSON.stringify({p,pred:c.test.map(t=>r.predictRidge(p,t,Infinity))}))"


def run_js(x, y, test):
    out = subprocess.run(["node", "-e", JS, str(RIDGE_JS)], input=json.dumps({"x": x, "y": y, "test": test}),
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def times(*stamps):
    return [moment_features(f"2026-{s}+09:00") for s in stamps]


def check(x, y, test):
    got, sk = run_js(x, y, test), ai.fit_preference(x, y)
    assert np.allclose(got["pred"], sk.predict(test), rtol=1e-6, atol=1e-6)
    return got, sk


def test_matches_sklearn_on_several_days():
    x = times("11-02T10:05:00", "11-02T14:30:00", "11-03T13:10:00", "11-04T15:20:00", "11-04T11:40:00")
    check(x, [-200, -300, 100, -150, 50], times("11-05T12:00:00", "11-05T16:00:00"))


def test_matches_sklearn_when_all_presses_are_on_one_day():
    # the season columns are constant: sklearn keeps their scale at 1 and so must the page
    x = times("11-04T11:00:00", "11-04T12:30:00", "11-04T14:05:00", "11-04T15:45:00")
    got, sk = check(x, [-100, -200, -300, -250], times("11-04T13:00:00", "11-04T17:00:00"))
    assert got["p"]["scale"][1] == 1 and got["p"]["scale"][2] == 1


def test_three_equal_presses_learn_a_constant():
    x = times("11-04T14:00:00", "11-04T14:01:00", "11-04T14:02:00")
    got, _ = check(x, [-200, -200, -200], times("11-04T14:10:00"))
    assert abs(got["pred"][0] + 200) < 1e-6


def test_far_inputs_are_held_inside_what_the_presses_covered():
    x = times("11-04T14:00:00", "11-04T14:01:00", "11-04T14:02:00")   # three presses within two minutes
    y = [-200, -300, -250]
    p = run_js(x, y, [])["p"]
    far = times("11-04T19:00:00")                                      # five hours later
    wild = LinearModel(p).predict(far, zmax=np.inf)[0]
    held = LinearModel(p).predict(far)[0]
    assert abs(wild + 250) > 1000 and abs(held + 250) < 100            # the plain Ridge swings, the held one stays near the mean
    js = subprocess.run(["node", "-e", f"const r=require(process.argv[1]);console.log(r.predictRidge({json.dumps(p)},{json.dumps(far[0])}))",
                         str(RIDGE_JS)], capture_output=True, text=True, check=True).stdout
    assert abs(float(js) - held) < 1e-6                                # JS and Python hold it the same way


def test_web_params_round_trip(tmp_path, monkeypatch):
    import live_learning
    monkeypatch.setattr(live_learning, "ROOT", tmp_path)
    x = times("11-02T10:05:00", "11-03T13:10:00", "11-04T15:20:00")
    p = run_js(x, [-200, 100, -150], [])["p"]
    path = save_params(p)
    model = LinearModel(json.loads(path.read_text()))
    test = times("11-05T12:00:00")
    assert np.allclose(model.predict(test), ai.fit_preference(x, [-200, 100, -150]).predict(test), atol=1e-6)
    for bad in ({**p, "scale": [0] * 6}, {**p, "n": 2}, {**p, "coef": [1] * 5}, {**p, "coef": [float("nan")] + p["coef"][1:]}):
        with pytest.raises(ValueError):
            save_params(bad)
    with pytest.raises(KeyError):
        save_params({})


def test_learn_payload_without_a_database(tmp_path):
    import sqlite3
    sqlite3.connect(tmp_path / "c.db").close()   # file exists, no corrections table yet
    out = learn_payload(tmp_path / "c.db")
    assert out["x"] == [] and len(out["now"]) == 6 and len(out["hours"]) == 13
