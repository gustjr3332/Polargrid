"""Virtual lecture room with a high south window nobody can reach: compare PolaGrid with the baselines.

Scenario: docs/PolaGrid_가상강의실_시나리오.md (Korean). Every number below is an ASSUMPTION of the virtual room,
not a measurement. Sky: KMA ASOS Seoul 2025 hourly (data/weather/kma_seoul_2025.csv, polagrid.weather).

    python tools/classroom_sim.py                # test days + replay day -> results/classroom_<mmdd>.txt
                                                 # and sw/app_ui/classroom/classroom_data.js (3D viewer input)
    python tools/classroom_sim.py --quick        # 2 test days, no AI (3): smoke run

Metrics (class hours 09:00-18:00, true physics, per-day averages):
glare desk-hours (summed over desks), target share (desk-steps with >= DESK_MIN_LUX and no glare, sun up),
mean desk lux, servo moves (whole 07:00-19:00 day, from evaluate.run_day).
"""
import dataclasses
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from polagrid import evaluate, online, physics, virtual, weather  # noqa: E402
from polagrid.physics import DESK_MIN_LUX, GLARE_LUX, KST, Room, sun_position, transmission, window_lux  # noqa: E402

# --- assumed room (all values are assumptions, see the scenario doc) ---------------------------------
ROWS, COLS, CELL = 5, 24, 0.3            # window band 7.2 m wide x 1.5 m tall, 120 cells of 0.3 m
SILL = 2.2                               # window bottom 2.2 m above the floor: out of reach
ROOM_W, ROOM_D, ROOM_H = 9.0, 7.2, 4.0   # only for drawing; the physics has no walls or reflections
DESKS = [(x, y, 1.8, 0.6, 0.75) for y in (1.5, 2.6, 3.7, 4.8, 5.9) for x in (-2.6, 0.0, 2.6)]  # 15 tables, 3 seats each
DESIGN = Room(rows=ROWS, cols=COLS, cell_w=CELL, cell_h=CELL, sill=SILL, desks=DESKS, glass=0.8)
# the built room differs a little from the drawing the AI starts from (same offsets as online.py)
REAL = dataclasses.replace(DESIGN, window_azimuth=DESIGN.window_azimuth + 8,
                           desks=[(x + 0.2, y - 0.2, w, d, h) for x, y, w, d, h in DESKS])
CLASS_START, CLASS_END = 9, 18
REPLAY_DAY = date(2025, 11, 4)           # clear day in the KMA data (mean kt 09-16 h = 0.98)
TEST_START, TEST_EVERY, TEST_COUNT = date(2025, 9, 1), 6, 18   # fall term; never a training day (those are Jan 1 + 6k)
AI3_DAYS = 60

# shortcut: memoise light_matrices per (room, time, sky) because run_day, online and the metrics ask for the same
# moment many times; holds about 30 kB per entry, fine for tens of days, drop it if memory gets tight.
_lm, _cache = physics.light_matrices, {}


def _cached(room, t, cloud=0.0):
    key = (id(room), t, id(cloud) if callable(cloud) else cloud)
    if key not in _cache:
        _cache[key] = _lm(room, t, cloud)
    return _cache[key]


physics.light_matrices = online.light_matrices = evaluate.light_matrices = _cached


def truth(room, t, cloud, trans):
    direct, diffuse = _cached(room, t, cloud)
    d = direct @ trans
    return d + diffuse @ trans, d


def run(room, day, cloud, make, seed, no_film=False):
    """One day of one method: run_day metrics + per-step trace (angles, desk lux, glare)."""
    m, log = evaluate.run_day(room, day, make(), cloud, seed=seed)
    t0 = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
    steps, glare_h, ok, lit, lux = [], 0.0, 0, 0, []
    for i, (_, angles) in enumerate(log):
        t = t0 + timedelta(minutes=i * evaluate.STEP_MIN)
        trans = np.full(room.n_cells, 1.0) if no_film else transmission(angles)  # no film: bare glass
        desk, direct = truth(room, t, cloud, trans)
        glare = direct > GLARE_LUX
        steps.append((t, angles, desk, glare))
        if CLASS_START <= t.hour < CLASS_END:
            glare_h += evaluate.STEP_MIN / 60 * glare.sum()
            lux.append(desk.mean())
            if sun_position(t, room.lat, room.lon)[0] > 0:
                ok += int(np.sum((desk >= DESK_MIN_LUX) & ~glare))
                lit += len(desk)
    return {"glare_h": glare_h, "target": ok / lit if lit else 0.0, "mean_lux": float(np.mean(lux)),
            "moves": 0 if no_film else m["moves"]}, steps


def methods(model):
    out = {
        "No film, blind out of reach": (lambda: evaluate.fixed_open, True),
        "Cells fixed open": (lambda: evaluate.fixed_open, False),
        "Time schedule 11-15 h": (lambda: evaluate.schedule, False),
        "PolaGrid AI (1)+(2) online": (lambda: online.polagrid_online(DESIGN), False),
    }
    if model is not None:
        out["PolaGrid AI (3) predict"] = (lambda: evaluate.polagrid_predict(model), False)
    return out


# reference row only (not in the replay): the same AI when the built room matches its drawing exactly
EXACT = "AI (1)+(2), room = drawing"


def main():
    quick = "--quick" in sys.argv
    started = time.time()
    model = None if quick else virtual.train(DESIGN, AI3_DAYS, jitter=False, sky="kma")
    _cache.clear()   # training skies are freed now; their ids could be reused by later sky functions
    ms = methods(model)
    test = weather.real_days("seoul", TEST_START, 2 if quick else TEST_COUNT, TEST_EVERY, source="kma")
    rows = {}
    for name, (make, bare) in ms.items():
        acc = [run(REAL, d, c, make, seed=i, no_film=bare)[0] for i, (d, c) in enumerate(test)]
        rows[name] = {k: float(np.mean([a[k] for a in acc])) for k in acc[0]}
    acc = [run(DESIGN, d, c, lambda: online.polagrid_online(DESIGN), seed=i)[0] for i, (d, c) in enumerate(test)]
    rows[EXACT] = {k: float(np.mean([a[k] for a in acc])) for k in acc[0]}
    replay_sky = weather.sky("seoul", REPLAY_DAY, "kma")
    replay = {name: run(REAL, REPLAY_DAY, replay_sky, make, seed=0, no_film=bare) for name, (make, bare) in ms.items()}

    # self-checks: bare glass lets in more beam than open films; shares are shares
    a, b = rows["No film, blind out of reach"], rows["Cells fixed open"]
    assert a["glare_h"] >= b["glare_h"] and all(0 <= r["target"] <= 1 for r in rows.values())

    stamp = date.today().strftime("%m%d")
    lines = [f"Virtual lecture room (ASSUMED, physics model only, not measured). {date.today()}",
             f"window: south (+8 deg in the built room), {COLS}x{ROWS} cells of {CELL} m, sill {SILL} m, glass 0.8; "
             f"{len(DESKS)} tables 1.8x0.6 m at 0.75 m (built room: moved 0.2 m); sky KMA ASOS Seoul 2025 hourly",
             f"test days: {len(test)} days from {TEST_START}, every {TEST_EVERY} days; class hours "
             f"{CLASS_START}-{CLASS_END} h; AI (3): {'off' if model is None else f'{AI3_DAYS} KMA days, design room'}",
             f"replay day {REPLAY_DAY} (KMA sky). glare = direct sun > {GLARE_LUX} lux on a desk; target = desk >= "
             f"{DESK_MIN_LUX} lux and no glare, share of desk-steps with sun up",
             "", f"{'method':<30}{'glare desk-h/day':>17}{'target share':>14}{'mean lux':>10}{'servo moves':>13}"]
    for tag, table in (("test-day average", rows),
                       (f"replay {REPLAY_DAY}", {k: v[0] for k, v in replay.items()})):
        lines.append(f"-- {tag}")
        lines += [f"{n:<30}{r['glare_h']:>17.2f}{r['target']:>14.2f}{r['mean_lux']:>10.0f}{r['moves']:>13.0f}"
                  for n, r in table.items()]
    lines.append(f"run time {time.time() - started:.0f} s")
    text = "\n".join(lines)
    print(text)
    if quick:
        return
    (HERE / "results" / f"classroom_{stamp}.txt").write_text(text + "\n", encoding="utf-8")

    first = next(iter(replay.values()))[1]
    data = {
        "note": "Virtual lecture room, all values assumed (physics model, KMA Seoul 2025 sky). Not measured.",
        "source": f"sw/edge_ai/tools/classroom_sim.py -> results/classroom_{stamp}.txt",
        "day": str(REPLAY_DAY), "room": {"w": ROOM_W, "d": ROOM_D, "h": ROOM_H, "window_azimuth": REAL.window_azimuth},
        "cells": [list(c) for c in REAL.cell_bounds()], "cell_cols": COLS, "desks": [list(d) for d in REAL.desks],
        "glare_lux": GLARE_LUX, "target_lux": DESK_MIN_LUX,
        "times": [t.strftime("%H:%M") for t, *_ in first],
        "sun": [[round(v, 1) for v in sun_position(t, REAL.lat, REAL.lon)] for t, *_ in first],
        "outdoor": [round(window_lux(REAL, t, replay_sky)) for t, *_ in first],
        "exact_room": {k: round(v, 3) for k, v in rows[EXACT].items()},
        "methods": {n: {"no_film": ms[n][1], "summary": {k: round(v, 3) for k, v in rows[n].items()},
                        "day": {k: round(v, 3) for k, v in r[0].items()},
                        "angles": [[round(float(a)) for a in s[1]] for s in r[1]],
                        "lux": [[round(float(v)) for v in s[2]] for s in r[1]],
                        "glare": [[int(g) for g in s[3]] for s in r[1]]} for n, r in replay.items()},
        "test_days": len(test),
    }
    out = HERE.parent / "app_ui" / "classroom" / "classroom_data.js"
    out.parent.mkdir(exist_ok=True)
    out.write_text("window.CLASSROOM = " + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
