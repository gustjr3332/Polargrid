"""PolaGrid AI: (1) cell contribution estimate, (2) angle decision, (3) next-day prediction and personalization.

(1) Desk lux is linear in cell transmission (see physics.py), so contributions come from
    non-negative least squares over probe readings (darken one cell at a time).
(2) Angles come from a linear program: least glare, desk at least min_lux, few servo moves.
    The controller only sees total desk lux, so glare is estimated as total lux above GLARE_LUX.
(3) One gradient boosting model, shared by all cells, learns the angles (2) chose from time, sun, outdoor light
    and where the sun ray through each cell lands,
    so later days need no probing. A Ridge model learns the user's brightness corrections.
"""
import math

import numpy as np
from scipy.optimize import linprog, nnls
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .physics import DESK_MIN_LUX, GLARE_LUX, T_LEAK, T_OPEN, transmission

T_MIN, T_MAX = T_LEAK, T_LEAK + T_OPEN


def to_angles(trans):
    """Inverse of physics.transmission: degrees for the given transmission(s)."""
    share = np.clip((np.asarray(trans) - T_LEAK) / T_OPEN, 0, 1)
    return np.degrees(np.arccos(np.sqrt(share)))


# (1) contribution estimate --------------------------------------------------------------

def probe_angles(n):
    """All open, then each cell closed alone: n + 1 angle settings."""
    rows = np.zeros((n + 1, n))
    rows[np.arange(1, n + 1), np.arange(n)] = 90.0
    return rows


def estimate_contributions(angle_rows, desk_lux_rows):
    """Contribution matrix A[M, N] (desk lux per unit transmission) from probe readings."""
    trans = transmission(np.asarray(angle_rows))
    lux = np.asarray(desk_lux_rows)
    return np.array([nnls(trans, lux[:, m])[0] for m in range(lux.shape[1])])


# (2) angle decision ---------------------------------------------------------------------

def decide_angles(contrib, prev_angles, min_lux=DESK_MIN_LUX, glare_lux=GLARE_LUX,
                  dark_weight=5.0, move_cost=125.0, open_bonus=10.0):
    """Cell angles that minimise glare + dark_weight * missing lux + servo moves.

    Variables: transmission T[N], glare slack g[M], missing-lux slack u[M], move size d[N].
    move_cost and open_bonus are in lux per unit transmission (moving one cell fully ~ 50 lux).
    """
    m, n = contrib.shape
    min_lux = np.broadcast_to(min_lux, (m,))
    t_prev = transmission(np.asarray(prev_angles, dtype=float))
    zm, zn, im, i_n = np.zeros((m, m)), np.zeros((m, n)), np.eye(m), np.eye(n)
    a_ub = np.block([
        [contrib, -im, zm, zn],          # A T - g <= glare_lux
        [-contrib, zm, -im, zn],         # min_lux - A T <= u
        [i_n, zn.T, zn.T, -i_n],         # T - T_prev <= d
        [-i_n, zn.T, zn.T, -i_n],        # T_prev - T <= d
    ])
    b_ub = np.concatenate([np.full(m, glare_lux), -min_lux, t_prev, -t_prev])
    cost = np.concatenate([np.full(n, -open_bonus), np.ones(m), np.full(m, dark_weight), np.full(n, move_cost)])
    bounds = [(T_MIN, T_MAX)] * n + [(0, None)] * (2 * m + n)
    res = linprog(cost, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if not res.success:                  # never expected; fall back to safe open state
        return np.zeros(n)
    return to_angles(res.x[:n])


# (3) prediction and personalization ---------------------------------------------------

def features(t, sun_alt, sun_az, outdoor_lux):
    """Model input for one moment: time of day, season, sun position, outdoor light on the window."""
    doy = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60
    return [hour, math.sin(2 * math.pi * doy / 365), math.cos(2 * math.pi * doy / 365),
            sun_alt, sun_az, outdoor_lux]


def cell_features(room, x):
    """One row per (moment, cell): the moment's features(), the cell centre (x, z) and where the sun ray through that
    centre lands at mean desk height (x, y). Sun behind the wall or below the horizon lands at 99 m (nowhere)."""
    x = np.atleast_2d(np.asarray(x, dtype=float))
    cells = np.array(room.cell_bounds())
    cx, cz = cells[:, :2].mean(1), cells[:, 2:].mean(1)
    alt, rel = np.radians(x[:, 3]), np.radians(x[:, 4] - room.window_azimuth)
    s_out, s_x, s_z = np.cos(alt) * np.cos(rel), np.cos(alt) * np.sin(rel), np.sin(alt)
    lit = (s_out > 0.02) & (s_z > 0.02)
    k = (cz[None, :] - np.mean([d[4] for d in room.desks])) / np.where(lit, s_z, 1.0)[:, None]  # ray length to desk height
    land_x = np.where(lit[:, None], cx[None, :] - k * s_x[:, None], 99.0)
    land_y = np.where(lit[:, None], k * s_out[:, None], 99.0)
    n, m = len(x), len(cx)
    return np.column_stack([np.repeat(x, m, 0), np.tile(cx, n), np.tile(cz, n), land_x.ravel(), land_y.ravel()])


class CellModel:
    """AI (3): one regressor shared by every cell of the room, on cell_features().

    Each cell sees the sun's landing point, so what the model learns (desks there, close the cell) holds for every
    cell. The old per-cell models had to learn every cell's sun window alone: on 10x10 cells they mixed up neighbours
    and left glare (100 cells over the CSE, 2026-11-05: 1.67 h old vs 0.00 h shared, results/closed_loop_ai3_1018.txt).
    """

    def __init__(self, room, seed=0):
        self.room, self.seed = room, seed

    def fit(self, x, angles):
        self.reg = HistGradientBoostingRegressor(max_iter=300, random_state=self.seed)
        self.reg.fit(cell_features(self.room, x), transmission(np.asarray(angles)).ravel())
        return self

    def predict(self, x):
        x = np.atleast_2d(x)
        return self.reg.predict(cell_features(self.room, x)).reshape(len(x), self.room.n_cells)


def fit_predictor(room, x, angles, seed=0):
    """Learn the angles chosen by (2) in `room`. x: rows of features(), angles: [rows, N]."""
    return CellModel(room, seed).fit(x, angles)


def predict_angles(model, x_row):
    return to_angles(np.clip(model.predict([x_row])[0], T_MIN, T_MAX))


def fit_preference(x, lux_offsets):
    """Learn how much brighter (+) or darker (-) the user wants the desk, from app corrections."""
    # scaled inputs: outdoor lux is ~1e4 while the other features are ~1, so unscaled Ridge extrapolates wildly
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(np.asarray(x), np.asarray(lux_offsets))


def preferred_min_lux(model, x_row):
    return max(0.0, DESK_MIN_LUX + float(model.predict([x_row])[0]))
