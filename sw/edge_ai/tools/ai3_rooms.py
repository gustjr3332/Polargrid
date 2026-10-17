"""AI (3) across different rooms under the same real sky (KMA ASOS Seoul 2025): does each room need its own model?

Rooms differ in window-to-desk distance (desk y offset), glass transmittance and a floor-level PROXY (horizon
obstruction angle, physics.Room.horizon; not a validated floor model). Same test dates and seeds as
ai3_weather_kma.py: 3 disjoint 20-day test sets (odd offsets) x 3 seeds (training dates on even offsets only).

    python tools/ai3_rooms.py > results/ai3_rooms_1017.txt
"""
import dataclasses
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai3_weather import fit, rows  # noqa: E402
from ai3_weather_kma import JAN1, MARGIN, SEEDS, SETS, header, stats, test_days, train_days  # noqa: E402
from polagrid import ai, evaluate, weather  # noqa: E402
from polagrid.physics import (DESK_MIN_LUX, GLARE_LUX, KST, Room, light_matrices, sun_position,  # noqa: E402
                              transmission, window_lux)

SEOUL = dataclasses.replace(Room(), lat=weather.SITES["seoul"][0], lon=weather.SITES["seoul"][1])


def room(horizon, glass, dy):
    return dataclasses.replace(SEOUL, horizon=horizon, glass=glass,
                               desks=[(x, y + dy, w, d, h) for x, y, w, d, h in SEOUL.desks])


# horizon 5 / 15 / 25 deg stands for high / mid / low floor; desks at y 0.6+1.6 m (near), 1.8+2.8 m (far)
ROOMS = {"R1 high clear near": room(5, 0.85, -0.4), "R2 low dark far": room(25, 0.45, 0.8),
         "R3 high dark far": room(5, 0.45, 0.8), "R4 low clear near": room(25, 0.85, -0.4),
         "R5 mid clear far": room(15, 0.85, 0.8), "R6 mid dark near": room(15, 0.45, -0.4)}
SOURCES = {"R0 nominal (old room)": SEOUL, **ROOMS}
_train, _test = {}, {}


def data(name, days):
    out = []
    for d, c in days:
        if (name, d) not in _train:
            _train[name, d] = rows(SOURCES[name], d, c, MARGIN, False)
        out += _train[name, d]
    return np.array([x for x, _ in out]), np.array([a for _, a in out])


def fine_days(n, seed):
    """n days of the test room spread over the year, even offsets (never a test date)."""
    step = 2 * (180 // n)
    return weather.real_days("seoul", JAN1 + timedelta(days=2 * seed), n, step, source="kma")


def test_cache(name, d, cloud):
    """Features and exact light matrices of every 5-min step of one test day (no sensor noise)."""
    if (name, d) not in _test:
        r, t = ROOMS[name], datetime(d.year, d.month, d.day, 7, tzinfo=KST)
        x, dirs, difs, up = [], [], [], []
        for _ in range(12 * 60 // evaluate.STEP_MIN):
            alt, az = sun_position(t, r.lat, r.lon)
            x.append(ai.features(t, alt, az, window_lux(r, t, cloud)))
            dr, df = light_matrices(r, t, cloud)
            dirs.append(dr), difs.append(df), up.append(alt > 0)
            t += timedelta(minutes=evaluate.STEP_MIN)
        _test[name, d] = np.array(x), np.array(dirs), np.array(difs), np.array(up)
    return _test[name, d]


def score(model, name, days):
    """Same metrics as ai3_weather.score (glare h, under-lit h, mean lux, moves per day), cached physics."""
    g = dk = lux = mv = 0.0
    for d, c in days:
        x, dirs, difs, up = test_cache(name, d, c)
        pred = ai.to_angles(np.clip(model.predict(x), ai.T_MIN, ai.T_MAX))
        cur, seq = np.zeros(pred.shape[1]), []
        for new in pred:
            nxt = np.where(np.abs(new - cur) < 5, cur, new)
            mv += np.sum(np.abs(nxt - cur) > 1)
            cur = nxt
            seq.append(cur)
        tr = transmission(np.array(seq))
        direct = np.einsum("smn,sn->sm", dirs, tr)
        desk = direct + np.einsum("smn,sn->sm", difs, tr)
        h = evaluate.STEP_MIN / 60
        g += h * np.sum(direct - GLARE_LUX > 0)
        dk += h * np.sum((desk < DESK_MIN_LUX) & up[:, None])
        lux += desk.mean()
    n = len(days)
    return g / n, dk / n, lux / n, mv / n


def runs(train, tests, kind="RF"):
    """train: seed -> [(source room name, days)]. One fit per seed, scored on the 3 test sets of each test room.
    tests: one room name (returns its runs) or a list (returns {name: runs})."""
    out = {b: [] for b in ([tests] if isinstance(tests, str) else tests)}
    for seed in SEEDS:
        parts = [data(n, d) for n, d in train(seed)]
        model = fit(kind, np.vstack([p[0] for p in parts]), np.vstack([p[1] for p in parts]), seed)
        for b in out:
            out[b] += [score(model, b, test_days("seoul", "kma", j)) for j in SETS]
    return out[tests] if isinstance(tests, str) else out


def own(name, n=60):
    return lambda s: [(name, train_days("seoul", "kma", n, s) if n == 60 else fine_days(n, s))]


def main():
    t0 = time.time()
    print("# AI (3) across rooms, 2026-10-17. Same real sky for every room: KMA ASOS Seoul 108, 2025 (kt per hour).")
    print("# 12 cells, 2 desks, south window, margin 2500 lux, base features, training 60 d unless noted.")
    print("# Room factors: glass = transmittance on light reaching the desks (the outdoor sensor feature and the")
    print("# 20,000 lux sun-on-window gate read light before the glass); desks near y 0.6/1.6 m, far 1.8/2.8 m (old 1.0/2.0);")
    print("# horizon = obstruction angle, a PROXY for floor level (5 high, 15 mid, 25 low): no direct sun below it,")
    print("# diffuse x (1 - sin h). It is not a measured or physically validated floor model. Virtual physics only.")
    print("# n = runs (3 disjoint 20-day test sets x 3 seeds); sd = population std over runs.")
    for k, r in SOURCES.items():
        print(f"# {k}: horizon {r.horizon:g} deg, glass {r.glass:g}, desk y {[d[1] for d in r.desks]}")

    header("Reference per test room (evaluate.run_day, 2% sensor noise)")
    for b, r in ROOMS.items():
        ctl = {"fixed open": lambda: evaluate.fixed_open, "AI (1)+(2) probe": lambda: evaluate.polagrid_probe(r.n_cells)}
        out = {k: [] for k in ctl}
        for j in SETS:
            for k, m in evaluate.compare(r, test_days("seoul", "kma", j), ctl).items():
                out[k].append((m["glare_h"], m["dark_h"], m["mean_lux"], m["moves"]))
        for k, v in out.items():
            stats(f"{b[:2]} {k}", v)

    for kind in ("RF", "HGB"):
        header(f"(a) train room A (60 d) -> test room B, {kind} base")
        mat = {}
        for a in SOURCES:
            res = runs(own(a), list(ROOMS), kind)
            for b in ROOMS:
                mat[a, b] = stats(f"{a[:2]} -> {b[:2]}{'  (same room)' if a == b else ''}", res[b])
        print(f"\n# {kind} glare h matrix (rows train, cols test); diag = same room")
        print(f"{'':>6}" + "".join(f"{b[:2]:>7}" for b in ROOMS))
        for a in SOURCES:
            print(f"{a[:2]:>6}" + "".join(f"{mat[a, b]:7.2f}" for b in ROOMS))
        for b in ROOMS:
            cross = [mat[a, b] for a in ROOMS if a != b]
            print(f"# test {b[:2]}: own {mat[b, b]:.2f}, other rooms mean {np.mean(cross):.2f} max {max(cross):.2f},"
                  f" R0 model {mat['R0 nominal (old room)', b]:.2f}")
        print(f"# [{time.time() - t0:.0f} s]", flush=True)

    header("(b) fine-tune with n days of test room B (RF base); 'A60+Bn' averaged over the 5 other rooms A")
    for b in ROOMS:
        for n in (7, 14, 30):
            stats(f"{b[:2]} own {n}d only", runs(own(b, n), b))
            pooled = [r for a in ROOMS if a != b for r in runs(lambda s, a=a: own(a)(s) + own(b, n)(s), b)]
            stats(f"{b[:2]} other A 60d + own {n}d (5 A)", pooled)
    print(f"# [{time.time() - t0:.0f} s]", flush=True)

    header("(c) pooled models (RF base): all 6 rooms x 60 d, and leave-one-out (the other 5 rooms x 60 d)")
    allr = runs(lambda s: [p for a in ROOMS for p in own(a)(s)], list(ROOMS))
    for b in ROOMS:
        stats(f"{b[:2]} pooled all 6 rooms", allr[b])
        stats(f"{b[:2]} pooled 5 others (new room)", runs(lambda s: [p for a in ROOMS if a != b for p in own(a)(s)], b))
    print(f"# total {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
