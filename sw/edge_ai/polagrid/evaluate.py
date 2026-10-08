"""Compare PolaGrid AI with the 3 baselines on simulated days (5-minute steps, 07:00-19:00).

Metrics come from the true physics (no sensor noise), per desk, summed over desks:
glare hours, under-lit hours (desk < DESK_MIN_LUX while the sun is up), mean desk lux, servo moves.

    python -m polagrid.evaluate
"""
from datetime import date, datetime, timedelta

import numpy as np

from . import ai
from .physics import (DESK_MIN_LUX, GLARE_LUX, KST, Room, light_matrices, simulate, sun_position, transmission,
                      window_lux)

STEP_MIN = 5
SUN_ON_WINDOW_LUX = 20_000  # blind baseline closes when outdoor light on the window is above this
GLARE_MARGIN_LUX = 1_000    # AI (2) aims this far below GLARE_LUX, because the sun moves between probes


def run_day(room, day, controller, cloud=0.0, noise=0.02, seed=0):
    """Run one day. controller(ctx) -> new angles, where ctx has t, features, angles, measure.

    Returns metrics and a log of (features, chosen angles) for training (3).
    """
    rng = np.random.default_rng(seed)
    angles = np.zeros(room.n_cells)
    moves = 0
    t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)

    def measure(new_angles):
        """Move the servos and read the sensors (probing goes through here, so its moves count)."""
        nonlocal angles, moves
        new_angles = np.asarray(new_angles, dtype=float)
        moves += int(np.sum(np.abs(new_angles - angles) > 1))
        angles = new_angles
        return simulate(room, t, angles, cloud, noise, rng)

    glare_h = dark_h = lux_sum = 0.0
    log = []
    for _ in range(12 * 60 // STEP_MIN):
        alt, az = sun_position(t, room.lat, room.lon)
        reading = simulate(room, t, angles, cloud, noise, rng)
        outdoor = float(np.mean(reading["cell_lux"] / transmission(angles)))
        x = ai.features(t, alt, az, outdoor)
        measure(controller({"t": t, "x": x, "outdoor": outdoor, "angles": angles, "measure": measure}))
        truth = simulate(room, t, angles, cloud)
        glare_h += STEP_MIN / 60 * np.sum(truth["glare"] > 0)
        if alt > 0:
            dark_h += STEP_MIN / 60 * np.sum(truth["desk_lux"] < DESK_MIN_LUX)
        lux_sum += truth["desk_lux"].mean()
        log.append((x, angles.copy()))
        t += timedelta(minutes=STEP_MIN)
    metrics = {"glare_h": glare_h, "dark_h": dark_h, "mean_lux": lux_sum / len(log), "moves": moves}
    return metrics, log


# baselines --------------------------------------------------------------------------------

def fixed_open(ctx):
    return np.zeros_like(ctx["angles"])


def blind(ctx):
    """Like an automatic blind: the whole window closes while strong sun hits it."""
    return np.full_like(ctx["angles"], 90.0 if ctx["outdoor"] > SUN_ON_WINDOW_LUX else 0.0)


def schedule(ctx):
    """Fixed timetable: whole window closed 11:00-15:00."""
    return np.full_like(ctx["angles"], 90.0 if 11 <= ctx["t"].hour < 15 else 0.0)


# PolaGrid -------------------------------------------------------------------------------------

def polagrid_probe(n_cells, probe_every_min=15):
    """AI (1) re-probes every probe_every_min minutes while sun hits the window, AI (2) decides every step.

    Without direct sun on the window there is no glare to find, so the cells just open.
    """
    state = {"contrib": None, "last": None}
    rows = ai.probe_angles(n_cells)

    def controller(ctx):
        t = ctx["t"]
        if ctx["outdoor"] <= SUN_ON_WINDOW_LUX:
            state["last"] = None
            return np.zeros(n_cells)
        if state["last"] is None or t - state["last"] >= timedelta(minutes=probe_every_min):
            before = ctx["angles"]
            lux = [ctx["measure"](a)["desk_lux"] for a in rows]
            ctx["measure"](before)          # go back before deciding, so the move cost is fair
            state["contrib"], state["last"] = ai.estimate_contributions(rows, lux), t
        return ai.decide_angles(state["contrib"], ctx["angles"], glare_lux=GLARE_LUX - GLARE_MARGIN_LUX)
    return controller


def teacher_log(room, day, cloud=0.0):
    """Training data for AI (3) without probing: AI (2) decisions from the exact contribution matrix.

    Same (features, angles) rows as run_day's log, but one light_matrices call per step instead of n + 1 probes.
    """
    angles = np.zeros(room.n_cells)
    log = []
    t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
    for _ in range(12 * 60 // STEP_MIN):
        alt, az = sun_position(t, room.lat, room.lon)
        outdoor = window_lux(room, t, cloud)
        if outdoor > SUN_ON_WINDOW_LUX:
            direct, diffuse = light_matrices(room, t, cloud)
            angles = ai.decide_angles(direct + diffuse, angles, glare_lux=GLARE_LUX - GLARE_MARGIN_LUX)
        else:
            angles = np.zeros(room.n_cells)
        log.append((ai.features(t, alt, az, outdoor), angles.copy()))
        t += timedelta(minutes=STEP_MIN)
    return log


def polagrid_predict(model):
    """AI (3): angles straight from the learned model, no probing. Changes under 5 deg are skipped."""
    def controller(ctx):
        new = ai.predict_angles(model, ctx["x"])
        return np.where(np.abs(new - ctx["angles"]) < 5, ctx["angles"], new)
    return controller


def lookup_table(logs):
    """Statistics baseline: mean transmission per (month, half hour) from past days."""
    def key(x):
        month = int((np.arctan2(x[1], x[2]) / (2 * np.pi) * 12) % 12)
        return month, int(x[0] * 2)
    groups = {}
    for x, angles in logs:
        groups.setdefault(key(x), []).append(transmission(angles))
    table = {k: np.mean(v, axis=0) for k, v in groups.items()}
    return lambda ctx: ai.to_angles(table.get(key(ctx["x"]), transmission(np.zeros_like(ctx["angles"]))))


# experiment --------------------------------------------------------------------------------

def days(start, count, every, seed):
    rng = np.random.default_rng(seed)
    return [(start + timedelta(days=i * every), float(rng.choice([0.0, 0.0, 0.3, 0.7]))) for i in range(count)]


def compare(room, test_days, controllers):
    rows = {}
    for name, make in controllers.items():
        total = {"glare_h": 0.0, "dark_h": 0.0, "mean_lux": 0.0, "moves": 0}
        for i, (day, cloud) in enumerate(test_days):
            m, _ = run_day(room, day, make(), cloud, seed=i)
            for k in total:
                total[k] += m[k] / len(test_days)
        rows[name] = total
    return rows


def main():
    room = Room()
    train = days(date(2026, 1, 1), 60, 6, seed=1)                      # spread over the year
    test = days(date(2026, 1, 4), 20, 18, seed=2)                      # other dates
    logs = []
    for i, (day, cloud) in enumerate(train):
        logs += run_day(room, day, polagrid_probe(room.n_cells), cloud, seed=100 + i)[1]
    model = ai.fit_predictor([x for x, _ in logs], [a for _, a in logs])
    table = lookup_table(logs)
    rows = compare(room, test, {
        "B0 fixed open": lambda: fixed_open,
        "B1 blind": lambda: blind,
        "B2 schedule": lambda: schedule,
        "Stats lookup table": lambda: table,
        "PolaGrid AI (1)+(2)": lambda: polagrid_probe(room.n_cells),
        "PolaGrid AI (3) predict": lambda: polagrid_predict(model),
    })
    print(f"{len(test)} test days, {len(train)} training days, 2 desks; per-day averages, desk-hours summed over desks")
    print(f"{'method':<24}{'glare h':>9}{'under-lit h':>13}{'mean lux':>10}{'servo moves':>13}")
    for name, r in rows.items():
        print(f"{name:<24}{r['glare_h']:>9.2f}{r['dark_h']:>13.2f}{r['mean_lux']:>10.0f}{r['moves']:>13.0f}")


if __name__ == "__main__":
    main()
