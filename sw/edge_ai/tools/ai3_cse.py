"""Why AI (3) lost to AI (1) in the 100-cell closed loop, measured on the direct physics path of closed_loop.py.

Same controller wrapping as closed_loop (evaluate.run_day, night mode, 2% sensor noise). Test skies: KMA Seoul 2025,
3 disjoint sets of 20 days (2025-01-04 + 6j + 18k), never a training date (training = 2025-01-01 + 6k, or the
synthetic random-cloud days of virtual.training_set). Separates the model (old per-cell boosting vs one model shared
by all cells, ai.CellModel), the hysteresis (old symmetric 5 deg vs close 3 / open 30) and the training data
(random cloud, jittered rooms, real KMA sky). One fit per row, n = 3 test sets.

    python tools/ai3_cse.py > results/ai3_cse_1018.txt
    python tools/ai3_cse.py --rest-10x10 >> results/ai3_cse_1018.txt   # 10x10 shared rows only (per-cell rows are slow)
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.multioutput import MultiOutputRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid import ai, evaluate, online, virtual, weather  # noqa: E402
from polagrid.physics import Room, transmission  # noqa: E402

JAN1 = date(weather.YEAR, 1, 1)
TESTS = [weather.real_days("seoul", JAN1 + timedelta(days=3 + 6 * j), 20, 18, source="kma") for j in range(3)]


def per_cell(x, angles):
    """ai.fit_predictor until 10-18: one boosting model per cell."""
    return MultiOutputRegressor(HistGradientBoostingRegressor(max_iter=200)).fit(x, transmission(angles))


def symmetric5(model):
    """evaluate.polagrid_predict until 10-18."""
    def controller(ctx):
        new = ai.predict_angles(model, ctx["x"])
        return np.where(np.abs(new - ctx["angles"]) < 5, ctx["angles"], new)
    return controller


def line(name, make, room):
    runs = [evaluate.compare(room, days, {"m": lambda: evaluate.night_closed(make())})["m"] for days in TESTS]
    r = {k: np.array([run[k] for run in runs]) for k in runs[0]}
    print(f"{name:<52}{r['glare_h'].mean():6.2f} +- {r['glare_h'].std():4.2f}{r['dark_h'].mean():9.2f}"
          f"{r['mean_lux'].mean():8.0f}{r['moves'].mean():8.0f}", flush=True)


def main():
    t0 = time.time()
    print("# AI (3) on the closed-loop direct path, 2026-10-18. Virtual physics only. Per-day means over 3 test sets of")
    print("# 20 KMA Seoul 2025 days (+- = std over the 3 sets), desk-hours summed over 2 desks, night mode on.")
    rest = "--rest-10x10" in sys.argv
    for rows, cols in ((10, 10),) if rest else ((3, 4), (10, 10)):
        room = Room(rows=rows, cols=cols)
        data = {"random cloud 60d": virtual.training_set(room, 60, jitter=False),
                "KMA sky 60d": virtual.training_set(room, 60, jitter=False, sky="kma")}
        if not rest:
            data["random cloud 120d jittered (1015 model)"] = virtual.training_set(room, 120, jitter=True)
        print(f"\n## {rows}x{cols} cells (data {time.time() - t0:.0f} s)")
        print(f"{'method':<52}{'glare h':>14}{'under-lit':>9}{'lux':>8}{'moves':>8}")
        if not rest:
            line("fixed open", lambda: evaluate.fixed_open, room)
            line("AI (1) online", lambda: online.polagrid_online(room), room)
        for dname, (x, a) in data.items():
            old, new = (None if rest else per_cell(x, a)), ai.fit_predictor(room, x, a)
            if not rest:
                line(f"{dname}: per-cell, sym 5 (old)", lambda: symmetric5(old), room)
                if dname.startswith("random cloud 120d"):
                    continue
                line(f"{dname}: per-cell, close 3/open 30", lambda: evaluate.polagrid_predict(old), room)
            line(f"{dname}: shared, sym 5", lambda: symmetric5(new), room)
            line(f"{dname}: shared, close 3/open 30 (new)", lambda: evaluate.polagrid_predict(new), room)
    print(f"\n# total {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
