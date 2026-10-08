from datetime import datetime

import numpy as np

from polagrid.ai import (decide_angles, estimate_contributions, features, fit_preference,
                         preferred_min_lux, probe_angles, to_angles)
from polagrid.physics import DESK_MIN_LUX, KST, Room, light_matrices, simulate, transmission

ROOM = Room()
NOON = datetime(2026, 11, 5, 13, tzinfo=KST)


def probe(room, t, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = probe_angles(room.n_cells)
    lux = [simulate(room, t, a, noise=noise, rng=rng)["desk_lux"] for a in rows]
    return estimate_contributions(rows, lux)


def test_to_angles_inverts_transmission():
    a = np.array([0, 30, 60, 90])
    assert np.allclose(to_angles(transmission(a)), a, atol=1e-6)


def test_contributions_match_physics_without_noise():
    direct, diffuse = light_matrices(ROOM, NOON)
    assert np.allclose(probe(ROOM, NOON), direct + diffuse, rtol=1e-6, atol=1e-6)


def test_contributions_find_the_sunlit_cells_with_noise():
    direct, _ = light_matrices(ROOM, NOON)
    est = probe(ROOM, NOON, noise=0.02)
    # 2% noise on ~18,000 lux hides cells that carry only a sliver of sun; the main ones must stand out
    main = direct[0] > 0.3 * direct[0].max()
    no_sun = direct[0] == 0
    assert est[0, main].min() > est[0, no_sun].max()


def test_decision_removes_glare_and_beats_closing_only_sunlit_cells():
    contrib = probe(ROOM, NOON)
    angles = decide_angles(contrib, np.zeros(ROOM.n_cells))
    out = simulate(ROOM, NOON, angles)
    assert out["glare"].max() == 0
    direct, _ = light_matrices(ROOM, NOON)
    crude = np.where(direct.sum(0) > 0, 90.0, 0.0)
    assert out["desk_lux"][0] > simulate(ROOM, NOON, crude)["desk_lux"][0]


def test_decision_keeps_cells_open_when_there_is_no_sun():
    evening = datetime(2026, 11, 5, 17, tzinfo=KST)
    angles = decide_angles(probe(ROOM, evening), np.zeros(ROOM.n_cells))
    assert angles.max() < 1


def test_decision_does_not_move_servos_for_nothing():
    contrib = probe(ROOM, NOON)
    first = decide_angles(contrib, np.zeros(ROOM.n_cells))
    assert np.allclose(decide_angles(contrib, first), first, atol=0.5)


def test_preference_learns_a_morning_boost():
    x, y = [], []
    for h in range(8, 18):
        x.append(features(datetime(2026, 11, 5, h, tzinfo=KST), 20, 180, 10_000))
        y.append(300 if h < 11 else 0)
    model = fit_preference(x, y)
    morning = preferred_min_lux(model, x[0])
    afternoon = preferred_min_lux(model, x[-1])
    assert morning > DESK_MIN_LUX + 100 and morning > afternoon
