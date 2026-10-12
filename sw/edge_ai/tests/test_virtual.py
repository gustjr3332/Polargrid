from datetime import datetime

import numpy as np
import pytest

from polagrid import online, virtual
from polagrid.ai import features, fit_preference
from polagrid.physics import KST, Room, light_matrices, simulate, transmission


def test_jitter_room_stays_close_to_the_original():
    room = Room()
    j = virtual.jitter_room(room, np.random.default_rng(0))
    assert abs(j.window_azimuth - room.window_azimuth) <= virtual.AZIMUTH_JITTER_DEG
    assert j.desks != room.desks and len(j.desks) == len(room.desks)


def test_saved_model_round_trips_and_checks_the_grid(tmp_path):
    room = Room(rows=2, cols=2)
    model = virtual.train(room, 2, jitter=True)
    path = virtual.save(model, room, 2, True, tmp_path / "m.joblib")
    x = [features(datetime(2026, 11, 5, 13, tzinfo=KST), 30, 180, 40_000)]
    assert np.allclose(virtual.load(room, path).predict(x), model.predict(x))
    with pytest.raises(ValueError):
        virtual.load(Room(rows=3, cols=3), path)


def test_online_filter_learns_a_wrong_prior_from_changing_angles():
    t = datetime(2026, 11, 5, 13, tzinfo=KST)
    direct, diffuse = light_matrices(Room(), t)
    true = direct + diffuse
    prior = true * 0.5                                    # the virtual room is off by half
    kf = online.ContributionFilter(*true.shape)
    rng = np.random.default_rng(0)
    for _ in range(60):
        trans = transmission(rng.uniform(0, 90, true.shape[1]))
        kf.update(prior, trans, true @ trans)
    trans = transmission(rng.uniform(0, 90, true.shape[1]))
    assert np.allclose(kf.matrix(prior) @ trans, true @ trans, rtol=0.02)


def test_preference_does_not_extrapolate_wildly():
    x = [features(datetime(2026, 11, 5, h, tzinfo=KST), 20 + h, 150 + h, 20_000 + 500 * h) for h in range(8, 13)]
    model = fit_preference(x, [-300.0] * 5)
    far = features(datetime(2026, 6, 20, 17, tzinfo=KST), 5, 280, 90_000)
    assert abs(model.predict([far])[0] + 300) < 100
