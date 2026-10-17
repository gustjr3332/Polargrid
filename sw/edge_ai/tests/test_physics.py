from datetime import datetime

import numpy as np
import pytest

from polagrid.physics import KST, Room, light_matrices, simulate, sun_position, transmission

ROOM = Room()


def max_altitude(month, day):
    return max(sun_position(datetime(2026, month, day, h, mi, tzinfo=KST), ROOM.lat, ROOM.lon)[0]
               for h in range(11, 14) for mi in range(0, 60, 2))


@pytest.mark.parametrize("month, day, expected", [
    (3, 20, 90 - 37.55),          # equinox
    (6, 21, 90 - 37.55 + 23.44),  # summer solstice
    (12, 21, 90 - 37.55 - 23.44),  # winter solstice
])
def test_noon_altitude(month, day, expected):
    assert max_altitude(month, day) == pytest.approx(expected, abs=1.0)


def test_morning_sun_is_in_the_east():
    alt, az = sun_position(datetime(2026, 3, 20, 8, tzinfo=KST), ROOM.lat, ROOM.lon)
    assert alt > 0 and 90 < az < 135


def test_transmission_follows_malus():
    t = transmission(np.array([0, 45, 90]))
    assert t[0] > t[1] > t[2]
    assert t[1] - t[2] == pytest.approx((t[0] - t[2]) / 2)


def test_desk_lux_is_linear_in_transmission():
    t = datetime(2026, 11, 5, 13, tzinfo=KST)
    angles = np.linspace(0, 90, ROOM.n_cells)
    direct, diffuse = light_matrices(ROOM, t)
    out = simulate(ROOM, t, angles)
    assert np.allclose(out["desk_lux"], (direct + diffuse) @ transmission(angles))


def test_closing_all_cells_removes_glare():
    t = datetime(2026, 11, 5, 13, tzinfo=KST)
    assert simulate(ROOM, t, np.zeros(ROOM.n_cells))["glare"].max() > 0
    assert simulate(ROOM, t, np.full(ROOM.n_cells, 90.0))["glare"].max() == 0


def test_darkening_one_cell_only_changes_its_own_share():
    t = datetime(2026, 11, 5, 13, tzinfo=KST)
    direct, diffuse = light_matrices(ROOM, t)
    base = simulate(ROOM, t, np.zeros(ROOM.n_cells))["desk_lux"]
    angles = np.zeros(ROOM.n_cells)
    angles[5] = 90
    drop = base - simulate(ROOM, t, angles)["desk_lux"]
    assert np.allclose(drop, (direct + diffuse)[:, 5] * (transmission(0) - transmission(90)))


def test_no_light_at_night_and_no_direct_sun_from_behind_the_wall():
    night = simulate(ROOM, datetime(2026, 11, 5, 22, tzinfo=KST), np.zeros(ROOM.n_cells))
    assert night["desk_lux"].max() == 0 and night["cell_lux"].max() == 0
    north = Room(window_azimuth=0)
    noon = simulate(north, datetime(2026, 11, 5, 12, 30, tzinfo=KST), np.zeros(north.n_cells))
    assert noon["desk_direct"].max() == 0 and noon["desk_lux"].min() > 0


def test_hourly_cloud_function_matches_constant_cloud():
    from datetime import date
    from polagrid import weather
    t = datetime(2026, 11, 5, 13, tzinfo=KST)
    a = simulate(ROOM, t, np.zeros(ROOM.n_cells), lambda _: 0.3)["desk_lux"]
    assert np.allclose(a, simulate(ROOM, t, np.zeros(ROOM.n_cells), 0.3)["desk_lux"])
    assert weather.cloud_of([0.2] * 24)(t) == pytest.approx(0.8)
    assert weather.clear_ghi(60) > 800 and weather.clear_ghi(0) == 0
    if weather.path("seoul").exists():                 # cached CSV is optional
        kt = weather.load_kt("seoul")[date(weather.YEAR, 6, 1)]
        assert len(kt) == 24 and all(0 <= k <= 1.2 for k in kt)
    if (weather.DATA_DIR / "kma_seoul_2025.csv").exists():   # not in git (KMA terms), fetched locally
        kma = weather.load_kt("seoul", source="kma")[date(weather.YEAR, 6, 1)]
        assert len(kma) == 24 and all(0 <= k <= 1.2 for k in kma)
        assert abs(sum(kma) - sum(kt)) < 0.3 * sum(kt)   # same sky from a station and from ERA5


def test_glass_scales_light_and_horizon_blocks_low_sun():
    t = datetime(2026, 12, 21, 12, 30, tzinfo=KST)                # noon sun about 29 deg up
    base = simulate(ROOM, t, np.zeros(ROOM.n_cells))
    dark = simulate(Room(glass=0.5), t, np.zeros(ROOM.n_cells))
    assert np.allclose(dark["desk_lux"], 0.5 * base["desk_lux"]) and base["desk_direct"].max() > 0
    low = simulate(Room(horizon=35), t, np.zeros(ROOM.n_cells))   # street-level proxy: sun hidden
    assert low["desk_direct"].max() == 0 and 0 < low["desk_lux"].min() < base["desk_lux"].min()
