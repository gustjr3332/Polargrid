"""AI (3) experiments with real hourly skies (polagrid/weather.py) instead of random cloud levels.

Train on real-weather or synthetic days, test on held-out real days (dates never used for training).
Metrics as virtual.score (true physics, no sensor noise, 5-degree hysteresis) plus servo moves.

    python tools/ai3_weather.py > results/ai3_weather_1017.txt
"""
import dataclasses
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.multioutput import MultiOutputRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polagrid import ai, evaluate, virtual, weather  # noqa: E402
from polagrid.physics import DESK_MIN_LUX, KST, Room, simulate, sun_position, transmission  # noqa: E402

Y = weather.YEAR
TRAIN_START, TEST_START = date(Y, 1, 1), date(Y, 1, 4)   # same date grids as evaluate.main, never overlapping


def site_room(site):
    lat, lon = weather.SITES[site]
    return dataclasses.replace(Room(), lat=lat, lon=lon)


def kt_at(cloud, t):
    c = cloud(t) if callable(cloud) else cloud
    return 1.0 - c


def rows(room, day, cloud, margin, extra):
    """(x, angles) of one teacher day; extra=True adds kt now, kt one hour ago."""
    log = evaluate.teacher_log(room, day, cloud, margin=margin)
    t0 = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
    out = []
    for i, (x, a) in enumerate(log):
        t = t0 + timedelta(minutes=evaluate.STEP_MIN * i)
        out.append((x + [kt_at(cloud, t), kt_at(cloud, t - timedelta(hours=1))] if extra else x, a))
    return out


def dataset(room, days, margin, extra):
    data = [r for d, c in days for r in rows(room, d, c, margin, extra)]
    return np.array([x for x, _ in data]), np.array([a for _, a in data])


def make(kind, seed=0):
    if kind == "HGB":                                 # per-cell model ai.fit_predictor used until 10-18 (1017 results)
        return MultiOutputRegressor(HistGradientBoostingRegressor(max_iter=200))
    if kind == "RF":
        return RandomForestRegressor(n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=seed)
    if kind == "GBR":
        return MultiOutputRegressor(GradientBoostingRegressor(n_estimators=300, max_depth=4, random_state=seed), n_jobs=-1)
    raise ValueError(kind)


def fit(kind, x, angles, seed=0):
    m = make(kind, seed)
    return m.fit(x, transmission(angles))


def score(model, room, test_days, extra, noise=0.0, seed=0):
    """Per-day glare h, under-lit h (desk-hours), mean desk lux, servo moves. noise: relative error of the
    outdoor-lux sensor feature (Gaussian, per step)."""
    rng = np.random.default_rng(seed)
    g = dk = lux = mv = 0.0
    for day, cloud in test_days:
        x = np.array([x for x, _ in rows(room, day, cloud, None, extra)])
        x[:, 5] *= np.maximum(0.0, 1 + noise * rng.standard_normal(len(x)))
        pred = ai.to_angles(np.clip(model.predict(x), ai.T_MIN, ai.T_MAX))
        cur = np.zeros(room.n_cells)
        t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
        for new in pred:
            nxt = np.where(np.abs(new - cur) < 5, cur, new)
            mv += np.sum(np.abs(nxt - cur) > 1)
            cur = nxt
            truth = simulate(room, t, cur, cloud)
            g += evaluate.STEP_MIN / 60 * np.sum(truth["glare"] > 0)
            if sun_position(t, room.lat, room.lon)[0] > 0:
                dk += evaluate.STEP_MIN / 60 * np.sum(truth["desk_lux"] < DESK_MIN_LUX)
            lux += truth["desk_lux"].mean() / len(pred)
            t += timedelta(minutes=evaluate.STEP_MIN)
    n = len(test_days)
    return g / n, dk / n, lux / n, mv / n


def line(name, r):
    print(f"{name:<46}{r[0]:>8.2f}{r[1]:>13.2f}{r[2]:>10.0f}{r[3]:>8.0f}", flush=True)


def header(title):
    print(f"\n## {title}\n{'method':<46}{'glare h':>8}{'under-lit h':>13}{'mean lux':>10}{'moves':>8}", flush=True)


def main():
    t_start = time.time()
    seoul = site_room("seoul")
    test = {s: weather.real_days(s, TEST_START, 20, 18) for s in weather.SITES}
    synth60 = evaluate.days(TRAIN_START, 60, 6, seed=1)
    real60 = {s: weather.real_days(s, TRAIN_START, 60, 6) for s in weather.SITES}
    real180 = weather.real_days("seoul", TRAIN_START, 180, 2)
    print("# AI (3) with real skies, 2026-10-17. Weather: Open-Meteo archive 2025 (ERA5, CC BY 4.0), kt = GHI / Haurwitz")
    print("# clear-sky GHI, cloud = 1 - kt per hour. 12 cells, 2 desks, south window. Test: 20 real days of the test site")
    print("# (2025-01-04 + 18k), train dates 2025-01-01 + 6k (60 d) or + 2k (180 d), never a test date. Per-day averages,")
    print("# desk-hours summed over desks. Margin = AI (3) teacher distance below the glare limit (lux). One run each.")

    header("Reference on the Seoul real test days (evaluate.run_day, 2% sensor noise)")
    ref = evaluate.compare(seoul, test["seoul"], {"fixed open": lambda: evaluate.fixed_open,
                                                   "AI (1)+(2) probe": lambda: evaluate.polagrid_probe(seoul.n_cells)})
    for k, r in ref.items():
        line(k, (r["glare_h"], r["dark_h"], r["mean_lux"], r["moves"]))

    header("Seoul test: training data x model x features (margin 2500)")
    sets = {"synthetic 60d": synth60, "real 60d": real60["seoul"], "real 180d": real180}
    cache = {}
    for sname, days in sets.items():
        for extra in (False, True):
            if extra and sname.startswith("synthetic"):
                fs = "+kt (constant per day)"
            else:
                fs = "+kt,kt-1h" if extra else "base"
            x, a = cache.setdefault((sname, extra), dataset(seoul, days, virtual.AI3_MARGIN_LUX, extra))
            for kind in ("HGB", "RF", "GBR"):
                if kind == "GBR" and sname == "real 180d":
                    continue                                  # slow and not needed for the comparison
                line(f"{sname} {kind} {fs}", score(fit(kind, x, a), seoul, test["seoul"], extra))

    header("Seoul test: margin sweep, real 60d, RF +kt,kt-1h")
    for margin in (1000, 2500, 4000, 6000):
        x, a = dataset(seoul, real60["seoul"], margin, True)
        line(f"margin {margin}", score(fit("RF", x, a), seoul, test["seoul"], True))

    header("Location transfer, real 60d, margin 2500, RF +kt,kt-1h")
    trained = {s: fit("RF", *dataset(site_room(s), real60[s], virtual.AI3_MARGIN_LUX, True)) for s in weather.SITES}
    for target in ("sejong", "jeju"):
        room = site_room(target)
        line(f"{target} test, Seoul model", score(trained["seoul"], room, test[target], True))
        line(f"{target} test, {target} model", score(trained[target], room, test[target], True))
        x1, a1 = dataset(seoul, real60["seoul"], virtual.AI3_MARGIN_LUX, True)
        x2, a2 = dataset(room, real60[target][:15], virtual.AI3_MARGIN_LUX, True)
        line(f"{target} test, Seoul 60d + {target} 15d", score(fit("RF", np.vstack([x1, x2]), np.vstack([a1, a2])),
                                                            room, test[target], True))
        ref = evaluate.compare(room, test[target], {"p": lambda: evaluate.polagrid_probe(room.n_cells)})["p"]
        line(f"{target} test, AI (1)+(2) probe", (ref["glare_h"], ref["dark_h"], ref["mean_lux"], ref["moves"]))
    line("seoul test, jeju model (reverse)", score(trained["jeju"], seoul, test["seoul"], True))

    model = fit("RF", *dataset(seoul, real60["seoul"], virtual.AI3_MARGIN_LUX, True))
    out = virtual.MODEL_DIR / "predictor_3x4_weather_seoul.joblib"
    joblib.dump({"model": model, "rows": 3, "cols": 4, "days": 60, "weather": "seoul_2025", "features": "base+kt,kt-1h"},
                out)
    print(f"\n# saved {out.name} (RF, real Seoul 60d, margin 2500). Total {time.time() - t_start:.0f} s")


if __name__ == "__main__":
    main()
