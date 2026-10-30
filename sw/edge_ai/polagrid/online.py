"""AI (1) without probing: estimate the contribution matrix from normal operating data.

Probing every cell costs n + 1 commands (O(N^2) notifications on 100 cells, see 0-4e). Instead the controller starts
from the virtual room's contribution matrix (physics.light_matrices at the current time, scaled by how clear the sky
is) and a Kalman filter learns the correction delta from each desk reading: reading = (prior + delta) @ T.
One reading per desk only tells the sum over cells, so the correction spreads over cells in proportion to their
uncertainty; cells whose angle changed in earlier steps (the AI (2) decisions) give the filter more to work with.
Optional dither closes one cell a little further each step so the filter also sees single-cell changes.

    python -m polagrid.online      # virtual room vs. a window turned 8 deg and desks moved 0.2 m
"""
import dataclasses
from datetime import date
from pathlib import Path

import numpy as np

from . import ai, evaluate
from .physics import GLARE_LUX, Room, light_matrices, transmission, window_lux


class ContributionFilter:
    """Kalman filter on delta[M, N]; all desks share the regressor T, so one covariance P[N, N] serves every desk."""

    def __init__(self, n_desks, n_cells, prior_sd=3000.0, drift_sd=300.0, noise=0.02):
        self.delta = np.zeros((n_desks, n_cells))
        self.p = np.eye(n_cells) * prior_sd ** 2
        self.drift, self.noise = drift_sd ** 2, noise

    def update(self, prior, trans, lux):
        """One desk reading `lux[M]` taken at transmissions `trans[N]`; `prior[M, N]` is the model matrix."""
        self.p += np.eye(len(trans)) * self.drift                 # the correction may drift as the sun moves
        resid = lux - (prior + self.delta) @ trans
        r = (self.noise * max(1.0, float(np.mean(lux)))) ** 2 + 25.0
        gain = self.p @ trans / (trans @ self.p @ trans + r)
        self.delta += np.outer(resid, gain)
        self.p -= np.outer(gain, trans @ self.p)

    def matrix(self, prior):
        return np.clip(prior + self.delta, 0.0, None)

    def save(self, path):
        """Keep what was learned (path ends in .npz) so a restarted controller does not begin from the virtual room again."""
        tmp = Path(path).with_suffix(".tmp.npz")
        np.savez(tmp, delta=self.delta, p=self.p)
        tmp.replace(path)

    def load(self, path):
        """Restore a saved state; False (nothing changed) when there is none or it is for another number of desks/cells."""
        try:
            with np.load(path) as f:
                delta, p = f["delta"], f["p"]
        except (OSError, KeyError, ValueError):
            return False
        if delta.shape != self.delta.shape or p.shape != self.p.shape:
            return False
        self.delta, self.p = delta, p
        return True


def model_prior(room_model, t, outdoor):
    """Contribution matrix of the virtual room, scaled by measured outdoor light / clear-sky outdoor light."""
    direct, diffuse = light_matrices(room_model, t)
    clear = window_lux(room_model, t)
    return (direct + diffuse) * min(1.0, outdoor / clear) if clear > 0 else direct + diffuse


def polagrid_prior_only(room_model):
    """Reference: trust the virtual room completely (no estimation)."""
    def controller(ctx):
        if ctx["outdoor"] <= evaluate.SUN_ON_WINDOW_LUX:
            return np.zeros_like(ctx["angles"])
        prior = model_prior(room_model, ctx["t"], ctx["outdoor"])
        return ai.decide_angles(prior, ctx["angles"], glare_lux=GLARE_LUX - evaluate.GLARE_MARGIN_LUX)
    return controller


def polagrid_online(room_model, dither_deg=0.0, state_path=None, glare_offset=None, save_every=10, **filter_args):
    """AI (1) online + AI (2). dither_deg > 0 closes one cell (round robin) that much further each sunny step.

    state_path (.npz): the filter is loaded from it at the first sunny step and saved every `save_every` updates.
    glare_offset(ctx) -> lux: AI (3), shifts the desk lux the angles aim below (negative = this user wants it darker)."""
    state = {"kf": None, "step": 0, "updates": 0}

    def controller(ctx):
        n = len(ctx["angles"])
        if ctx["outdoor"] <= evaluate.SUN_ON_WINDOW_LUX:
            return np.zeros(n)
        prior = model_prior(room_model, ctx["t"], ctx["outdoor"])
        if state["kf"] is None:
            state["kf"] = ContributionFilter(prior.shape[0], n, **filter_args)
            if state_path:
                state["kf"].load(state_path)
        state["kf"].update(prior, transmission(ctx["angles"]), ctx["desk_lux"])
        state["updates"] += 1
        if state_path and state["updates"] % save_every == 0:
            state["kf"].save(state_path)
        limit = GLARE_LUX - evaluate.GLARE_MARGIN_LUX
        if glare_offset:
            limit = max(200.0, limit + glare_offset(ctx))   # same floor as prefs.run_day
        angles = ai.decide_angles(state["kf"].matrix(prior), ctx["angles"], glare_lux=limit)
        if dither_deg:
            angles[state["step"] % n] = min(90.0, angles[state["step"] % n] + dither_deg)
            state["step"] += 1
        return angles
    return controller


def main():
    room_model = Room()
    real = dataclasses.replace(room_model, window_azimuth=room_model.window_azimuth + 8,
                               desks=[(x + 0.2, y - 0.2, w, d, h) for x, y, w, d, h in room_model.desks])
    test = evaluate.days(date(2026, 1, 4), 8, 45, seed=2)
    rows = evaluate.compare(real, test, {
        "fixed open": lambda: evaluate.fixed_open,
        "prior only (virtual room)": lambda: polagrid_prior_only(room_model),
        "online AI (1)": lambda: polagrid_online(room_model),
        "online AI (1) + dither 20": lambda: polagrid_online(room_model, 20.0),
        "probe every 15 min": lambda: evaluate.polagrid_probe(real.n_cells, 15),
    })
    print(f"real room differs from the virtual room (window +8 deg, desks moved); {len(test)} test days, per-day averages")
    print(f"{'method':<28}{'glare h':>9}{'under-lit h':>13}{'mean lux':>10}{'servo moves':>13}")
    for name, r in rows.items():
        print(f"{name:<28}{r['glare_h']:>9.2f}{r['dark_h']:>13.2f}{r['mean_lux']:>10.0f}{r['moves']:>13.0f}")


if __name__ == "__main__":
    main()
