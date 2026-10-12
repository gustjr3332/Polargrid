"""AI (3) personalization on virtual users: how many app corrections until the system stops needing them.

A virtual user finds the desk too bright earlier than the default does: tolerated desk lux while the sun is on the
window is TOLERANCE_LUX + offset(hour), with a negative offset ("light sensitive": -300 lux all day; "afternoon
sensitive": 0 at 07:00 falling to -400 at 19:00). Whenever the desk is brighter than the user tolerates, the user
corrects once (an episode of too-bright steps = one correction) and the app logs the wanted offset with the moment's
features. fit_preference learns from the logged corrections; the controller then asks AI (2) for a lower glare
limit by the predicted offset.
A first version raised the minimum desk lux instead (ai.preferred_min_lux). It never triggered: in this virtual room
the desks are bright enough whenever opening every cell can make them so, because AI (2) only closes cells to cut
glare. Virtual users are not real preferences: this checks the mechanism and how many corrections it needs.

    python -m polagrid.prefs
"""
from datetime import date, datetime, timedelta

import numpy as np

from . import ai, evaluate
from .physics import GLARE_LUX, KST, Room, light_matrices, simulate, sun_position, window_lux

TOLERANCE_LUX = GLARE_LUX - evaluate.GLARE_MARGIN_LUX   # desk lux the controller aims below by default
USERS = {
    "light sensitive": lambda hour: -300.0,
    "afternoon sensitive": lambda hour: -400.0 * (hour - 7) / 12,
}
DAYLIGHT_LUX = 2000.0         # AI (2) runs whenever the window gets at least this much light
CORRECTION_NOISE_LUX = 30.0   # the slider is not exact


def run_day(room, day, cloud, offset_fn, pref_model):
    """One day with exact contributions. Returns too-bright desk-hours for this user, corrections, glare hours, samples."""
    angles = np.zeros(room.n_cells)
    t = datetime(day.year, day.month, day.day, 7, tzinfo=KST)
    bright_h = glare_h = 0.0
    samples, was_bright = [], False
    noise = np.random.default_rng(day.toordinal())
    for _ in range(12 * 60 // evaluate.STEP_MIN):
        alt, az = sun_position(t, room.lat, room.lon)
        outdoor = window_lux(room, t, cloud)
        x = ai.features(t, alt, az, outdoor)
        sunny = outdoor > DAYLIGHT_LUX   # not only direct sun: a bright overcast sky can also be too much for this user
        if sunny:
            direct, diffuse = light_matrices(room, t, cloud)
            limit = TOLERANCE_LUX + (float(np.clip(pref_model.predict([x])[0], -1000, 1000)) if pref_model else 0.0)
            angles = ai.decide_angles(direct + diffuse, angles, glare_lux=max(200.0, limit))
        else:
            angles = np.zeros(room.n_cells)
        truth = simulate(room, t, angles, cloud)
        offset = offset_fn(t.hour + t.minute / 60)
        too_bright = (truth["desk_lux"] > TOLERANCE_LUX + offset + 50) if sunny else np.zeros(len(truth["desk_lux"]), bool)
        if too_bright.any() and not was_bright:
            samples.append((x, offset + noise.normal(0, CORRECTION_NOISE_LUX)))
        was_bright = bool(too_bright.any())
        bright_h += evaluate.STEP_MIN / 60 * np.sum(too_bright)
        glare_h += evaluate.STEP_MIN / 60 * np.sum(truth["glare"] > 0)
        t += timedelta(minutes=evaluate.STEP_MIN)
    return bright_h, len(samples), glare_h, samples


def trial(room, offset_fn, use_days, test_days):
    """Use the system for `use_days` days (user corrects, model refits daily), then measure on the test days."""
    xs, ys, model = [], [], None
    for day, cloud in use_days:
        samples = run_day(room, day, cloud, offset_fn, model)[3]
        xs += [x for x, _ in samples]
        ys += [y for _, y in samples]
        if len(xs) >= 3:
            model = ai.fit_preference(xs, ys)
    out = np.array([run_day(room, d, c, offset_fn, model)[:3] for d, c in test_days]).mean(axis=0)
    return out, len(ys)


def main():
    room = Room()
    use = evaluate.days(date(2026, 3, 1), 40, 5, seed=3)
    test = evaluate.days(date(2026, 3, 3), 10, 17, seed=4)
    print("virtual users, 2 desks, per test day (desk-hours); a correction = one too-bright episode the user fixes by hand")
    print(f"{'user':<20}{'use days':>9}{'logged corr.':>14}{'too bright h':>14}{'corrections/day':>17}")
    for name, fn in USERS.items():
        for n in (0, 5, 15, 40):
            (bright, corr, _), logged = trial(room, fn, use[:n], test)
            print(f"{name:<20}{n:>9}{logged:>14}{bright:>14.2f}{corr:>17.2f}")


if __name__ == "__main__":
    main()
