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


def test_fail_open_opens_on_any_fault_and_passes_good_answers():
    from polagrid.evaluate import fail_open
    ctx = {"angles": np.array([30.0, 60.0]), "desk_lux": np.array([800.0])}
    good = fail_open(lambda c: np.array([45.0, 90.0]))
    assert np.array_equal(good(ctx), [45.0, 90.0]) and good.opens == 0
    for bad in (lambda c: np.array([np.nan, 10.0]), lambda c: np.array([10.0, 95.0]), lambda c: np.array([-1.0, 0.0]),
                lambda c: np.array([10.0]), lambda c: 1 / 0):
        w = fail_open(bad)
        assert np.array_equal(w(ctx), [0.0, 0.0]) and w.opens == 1
    for lux in (np.array([np.nan]), np.array([-5.0]), np.array([1e9])):          # a broken desk reading
        w = fail_open(lambda c: np.array([45.0, 45.0]))
        assert np.array_equal(w({**ctx, "desk_lux": lux}), [0.0, 0.0]) and w.opens == 1
    assert np.array_equal(fail_open(lambda c: np.array([45.0, 45.0]))({"angles": ctx["angles"]}), [45.0, 45.0])   # no desk key


def test_night_mode_closes_everything_only_when_dark():
    from polagrid.evaluate import NIGHT_LUX, night_closed
    control = night_closed(lambda ctx: np.zeros_like(ctx["angles"]))
    angles = np.zeros(4)
    assert np.all(control({"outdoor": NIGHT_LUX - 1, "angles": angles}) == 90)
    assert np.all(control({"outdoor": NIGHT_LUX + 1, "angles": angles}) == 0)


def test_cell_features_land_the_sun_ray_on_the_desk_it_lights():
    from polagrid.ai import cell_features
    from polagrid.physics import sun_position
    alt, az = sun_position(NOON, ROOM.lat, ROOM.lon)
    rows = cell_features(ROOM, [features(NOON, alt, az, 50_000)])
    assert rows.shape == (ROOM.n_cells, 10)
    direct, _ = light_matrices(ROOM, NOON)
    for m, (cx, cy, w, d, _) in enumerate(ROOM.desks):
        for i in np.flatnonzero(direct[m] > 0.5 * direct[m].max()):     # cells that mostly light desk m
            assert abs(rows[i, 8] - cx) < w / 2 + 0.3 and abs(rows[i, 9] - cy) < d / 2 + 0.3
    night = cell_features(ROOM, [features(NOON, -10, az, 0)])
    assert (night[:, 8:] == 99).all()


def test_shared_predictor_learns_a_table_and_predict_errs_to_closing():
    from polagrid.ai import fit_predictor, predict_angles
    from polagrid.evaluate import PREDICT_OPEN_DEG, polagrid_predict
    room = Room(rows=2, cols=2)
    x = [features(NOON, 30 + h / 10, 180, 50_000) for h in range(100)]
    target = np.array([[90.0, 0.0, 90.0, 0.0]] * 100)
    model = fit_predictor(room, x, target)
    assert model.predict(x).shape == (100, 4)
    assert np.allclose(predict_angles(model, x[0]), target[0], atol=10)
    cur = np.array([70.0, 20.0, 90.0, 60.0])           # model wants 90, 0, 90, 0 (left column closed)
    out = polagrid_predict(model)({"x": x[0], "angles": cur})
    assert out[0] > 80                       # closing by 20 deg: follows the model
    assert out[1] == 20.0                    # opening by 20 deg: under PREDICT_OPEN_DEG, stays put
    assert out[3] < 10 and 60 >= PREDICT_OPEN_DEG   # opening by 60 deg: follows
