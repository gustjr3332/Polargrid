"""PolaGrid virtual physics model: sun position, polarizer transmission, cell -> desk illuminance.

Model (all assumptions, to be replaced by measured values once hardware exists):
- Sun position: NOAA low-precision formulas (about 0.5 deg error).
- Outdoor light, clear sky: direct normal = 125,000 lx * 0.7**(AM**0.678) (Meinel, x ~93 lm/W),
  diffuse horizontal = 15,000 lx * sin(alt)**0.5. `cloud` (0..1) moves light from direct to diffuse.
- Window: vertical plane y = 0, room interior is y > 0, z is up. Cells form a rows x cols grid.
- Cell transmission: T(theta) = T_OPEN * cos^2(theta) + T_LEAK (Malus's law), theta in 0..90 deg.
- Desk illuminance is linear in T: desk_lux = (direct + diffuse) @ T(angles).
  direct[m, n] = share of desk m's sample points that see the sun through cell n, times direct lux.
  diffuse[m, n] = uniform-sky luminance through cell n, small-source approximation.
- Glare on a desk = direct sun lux above GLARE_LUX.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

T_OPEN = 0.40      # two aligned polarizing films let through about 40% of natural light
T_LEAK = 0.005     # crossed films still leak a little
GLARE_LUX = 2000   # direct sun on a desk above this counts as glare (assumption)
DESK_MIN_LUX = 500  # desk is bright enough to work without lights
KST = timezone(timedelta(hours=9))  # Korea has no daylight saving time


@dataclass
class Room:
    lat: float = 37.5503          # Sejong University, Seoul
    lon: float = 127.0731
    window_azimuth: float = 180.0  # direction the window faces, deg from north (180 = south)
    rows: int = 3
    cols: int = 4
    cell_w: float = 0.3            # m
    cell_h: float = 0.3
    sill: float = 0.9              # height of the window bottom, m
    # desks as (center x, center y, width, depth, height), m
    desks: list = field(default_factory=lambda: [(-0.3, 1.0, 0.8, 0.5, 0.75),
                                                 (0.6, 2.0, 0.8, 0.5, 0.75)])
    samples: int = 5               # sample points per desk side

    @property
    def n_cells(self):
        return self.rows * self.cols

    def cell_bounds(self):
        """(x0, x1, z0, z1) for each cell, row 0 at the bottom, numbered row by row."""
        x_left = -self.cols * self.cell_w / 2
        return [(x_left + c * self.cell_w, x_left + (c + 1) * self.cell_w,
                 self.sill + r * self.cell_h, self.sill + (r + 1) * self.cell_h)
                for r in range(self.rows) for c in range(self.cols)]

    def desk_points(self, m):
        cx, cy, w, d, h = self.desks[m]
        s = (np.arange(self.samples) + 0.5) / self.samples - 0.5
        xs, ys = np.meshgrid(cx + s * w, cy + s * d)
        return np.column_stack([xs.ravel(), ys.ravel(), np.full(xs.size, h)])


def sun_position(t: datetime, lat: float, lon: float):
    """Sun (altitude, azimuth) in degrees. Azimuth from north, clockwise. t must be timezone-aware."""
    t = t.astimezone(timezone.utc)
    doy = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60 + t.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    ha = math.radians((hour * 60 + eqtime + 4 * lon) / 4 - 180)
    la = math.radians(lat)
    cos_zen = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1.0, min(1.0, cos_zen)))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(decl) * math.cos(la))) + 180
    return 90 - math.degrees(zen), az % 360


def outdoor_light(alt: float, cloud: float = 0.0):
    """(direct normal lux, diffuse horizontal lux) for sun altitude in degrees."""
    if alt <= 0:
        return 0.0, 0.0
    s = math.sin(math.radians(alt))
    air_mass = 1 / (s + 0.50572 * (alt + 6.07995) ** -1.6364)
    direct = 125_000 * 0.7 ** (air_mass ** 0.678)
    diffuse = 15_000 * s ** 0.5
    return direct * (1 - cloud), diffuse + direct * s * cloud * 0.5


def transmission(angles):
    """Light share through a cell for angle(s) in degrees (0 = open, 90 = closed)."""
    return T_OPEN * np.cos(np.radians(angles)) ** 2 + T_LEAK


def light_matrices(room: Room, t: datetime, cloud: float = 0.0):
    """direct[M, N] and diffuse[M, N]: desk lux from each cell when its transmission is 1."""
    alt, az = sun_position(t, room.lat, room.lon)
    e_dn, e_dh = outdoor_light(alt, cloud)
    cells = room.cell_bounds()
    n, m_count = room.n_cells, len(room.desks)
    direct, diffuse = np.zeros((m_count, n)), np.zeros((m_count, n))
    rel = math.radians(az - room.window_azimuth)
    a = math.radians(alt)
    s_out, s_x, s_z = math.cos(a) * math.cos(rel), math.cos(a) * math.sin(rel), math.sin(a)
    sky_luminance = e_dh / math.pi
    for m in range(m_count):
        pts = room.desk_points(m)
        if e_dn > 0 and s_out > 0:
            k = pts[:, 1] / s_out                  # distance along the sun ray to the window plane
            hx, hz = pts[:, 0] + k * s_x, pts[:, 2] + k * s_z
            for i, (x0, x1, z0, z1) in enumerate(cells):
                hit = (hx >= x0) & (hx < x1) & (hz >= z0) & (hz < z1)
                direct[m, i] = hit.mean() * e_dn * s_z   # horizontal desk receives sin(alt) of the beam
        for i, (x0, x1, z0, z1) in enumerate(cells):
            v = np.array([(x0 + x1) / 2, 0.0, (z0 + z1) / 2]) - pts
            r = np.linalg.norm(v, axis=1)
            cos_w, cos_d = -v[:, 1] / r, np.clip(v[:, 2] / r, 0, None)
            diffuse[m, i] = np.mean(sky_luminance * room.cell_w * room.cell_h * cos_w * cos_d / r ** 2)
    return direct, diffuse


def window_lux(room: Room, t: datetime, cloud: float = 0.0):
    """Outdoor light falling on the window plane (lux), before the polarizers."""
    alt, az = sun_position(t, room.lat, room.lon)
    e_dn, e_dh = outdoor_light(alt, cloud)
    rel = math.radians(az - room.window_azimuth)
    return e_dn * max(0.0, math.cos(math.radians(alt)) * math.cos(rel)) + e_dh / 2


def simulate(room: Room, t: datetime, angles, cloud: float = 0.0, noise: float = 0.0, rng=None):
    """Sensor readings for one moment. angles: N cell angles in degrees.

    Returns desk_lux[M], desk_direct[M], glare[M] (lux above GLARE_LUX), cell_lux[N].
    noise is the relative sensor noise (0.02 = 2%).
    """
    tr = transmission(np.asarray(angles, dtype=float))
    direct, diffuse = light_matrices(room, t, cloud)
    desk_direct = direct @ tr
    desk_lux = desk_direct + diffuse @ tr
    cell_lux = tr * window_lux(room, t, cloud)
    if noise:
        rng = rng or np.random.default_rng()
        desk_lux = desk_lux * (1 + rng.normal(0, noise, desk_lux.shape))
        cell_lux = cell_lux * (1 + rng.normal(0, noise, cell_lux.shape))
    return {"desk_lux": desk_lux, "desk_direct": desk_direct,
            "glare": np.clip(desk_direct - GLARE_LUX, 0, None), "cell_lux": cell_lux}


if __name__ == "__main__":
    room = Room()
    day = datetime(2026, 11, 5, tzinfo=KST)
    print("time   alt    az  | all open: desk lux (glare)      | all closed: desk lux")
    for h in range(8, 18):
        t = day + timedelta(hours=h)
        alt, az = sun_position(t, room.lat, room.lon)
        o = simulate(room, t, np.zeros(room.n_cells))
        c = simulate(room, t, np.full(room.n_cells, 90.0))
        opened = "  ".join(f"{l:6.0f}({g:5.0f})" for l, g in zip(o["desk_lux"], o["glare"]))
        closed = "  ".join(f"{l:6.0f}" for l in c["desk_lux"])
        print(f"{h:02d}:00 {alt:5.1f} {az:5.1f} | {opened} | {closed}")
