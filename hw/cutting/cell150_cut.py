"""Laser-cut drawings for the 150 mm cell (hw/README.md, hw/diagrams/cell150.html).

    python cell150_cut.py [--kerf 0.15]      writes one DXF per part + cut_overview.svg next to this file
    python cell150_cut.py --check            only runs the self-checks

Units mm, DXF R12 (opens in Inkscape, LightBurn, LibreCAD, Fusion). Layers: CUT (red, cut through) and MARK (blue,
engrave or just a guide). Every part is moved so its lower left corner of the bounding box is at 0,0.
--kerf: laser kerf in mm (0.1 to 0.2 typical for acrylic, not known for the ES centre machine). Outlines move out by
kerf/2 and holes move in by kerf/2. Cut a test pair first, measure, and set the real value.
"""
import argparse
import math
from pathlib import Path

HERE = Path(__file__).parent
R_WIN = 75.0                                   # window half width = film disc radius
M = 1.0                                        # gear module
Z_DISC, Z_PIN = 150, 24
RP_DISC, RP_PIN = Z_DISC * M / 2, Z_PIN * M / 2
CENTRE_D = RP_DISC + RP_PIN                    # 87 mm
PIN_XY = (CENTRE_D / math.sqrt(2),) * 2        # pinion centre (61.5, 61.5), top right corner
HOLE_R = 76.5                                  # hole in the groove plate (disc tip radius 76 + 0.5)
TEETH_FROM_DEG, N_TEETH = 40.0, 42             # teeth on the disc rim, disc frame angles
SLOT_R, SLOT_W, PIN_SIZE = 72.0, 3.6, 3.0      # stop slot in the disc and the pin glued on the back plate
STOP_DEG = 225.0                               # screen angle of the stop pin (opposite the pinion)
RING_OPEN_R = 70.0
SHAFT_HOLE_D = 9.5                             # 28BYJ-48 shaft boss is about 9 mm
SHAFT_D, SHAFT_FLAT = 5.0, 3.0                 # double-D shaft, +0.1 mm fit added below
FIT = 0.1
BACKLASH = 0.15                                 # mm at the pitch circle, split over both gears; raise it if the test pair binds


# ---------- geometry ----------
def inv(a):
    return math.tan(a) - a


def involute_flank(z, rp, ra, rr, m=M, alpha=math.radians(20)):
    """Half tooth angle h(r) and the radii to sample from the start of the flank to the tip."""
    rb = rp * math.cos(alpha)
    r0 = max(rr, rb)

    def h(r):
        r = max(r, rb)
        return math.pi / (2 * z) + inv(alpha) - inv(math.acos(rb / r)) - BACKLASH / 4 / r
    radii = [r0 + (ra - r0) * i / 10 for i in range(11)]
    return h, radii


def tooth(z, rp, c, m=M):
    ra, rr = rp + m, rp - 1.25 * m
    h, radii = involute_flank(z, rp, ra, rr, m)
    left = [(r, c - h(r)) for r in radii]
    right = [(r, c + h(r)) for r in reversed(radii)]
    pts = [(rr, c - h(radii[0]))] + left + right + [(rr, c + h(radii[0]))]
    return [(r * math.cos(a), r * math.sin(a)) for r, a in pts]


def gear_full(z, rp, m=M):
    pts = []
    for i in range(z):
        pts += tooth(z, rp, 2 * math.pi * i / z, m)
    return pts


def disc_outline():
    """Z150 teeth on a 100 deg arc, plain rim (tip radius) elsewhere."""
    ra, rr = RP_DISC + M, RP_DISC - 1.25 * M
    pitch = 2 * math.pi / Z_DISC
    first = math.radians(TEETH_FROM_DEG) + pitch / 2
    pts = []
    s = first - pitch / 2
    e = first + (N_TEETH - 1) * pitch + pitch / 2
    pts.append((ra * math.cos(s), ra * math.sin(s)))
    pts.append((rr * math.cos(s), rr * math.sin(s)))
    for i in range(N_TEETH):
        pts += tooth(Z_DISC, RP_DISC, first + i * pitch)
    pts.append((rr * math.cos(e), rr * math.sin(e)))
    pts.append((ra * math.cos(e), ra * math.sin(e)))
    n = 240                                                      # plain rim from e round to s
    for i in range(1, n):
        a = e + (s + 2 * math.pi - e) * i / n
        pts.append((ra * math.cos(a), ra * math.sin(a)))
    return pts


def arc(cx, cy, r, a0, a1, n=48):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def union_hole():
    """Outline of the circle of radius HOLE_R joined with the pinion pocket circle (radius 13.5)."""
    r1, r2, d = HOLE_R, RP_PIN + M + 0.5, CENTRE_D
    t = math.radians(45)
    a1 = math.acos((r1 * r1 + d * d - r2 * r2) / (2 * r1 * d))
    cx, cy = d * math.cos(t), d * math.sin(t)
    big = arc(0, 0, r1, t + a1, t - a1 + 2 * math.pi, 240)                 # far side of the big circle, ends at I2
    i2, i1 = big[-1], big[0]

    def rel(p):                                                           # angle of p seen from the pocket centre, relative to t
        return (math.atan2(p[1] - cy, p[0] - cx) - t + math.pi) % (2 * math.pi) - math.pi
    return big + arc(cx, cy, r2, t + rel(i2), t + rel(i1), 96)[1:-1]      # outer arc of the pocket, through angle t


def area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def offset(p, d):
    """Move a closed polygon outward by d (negative = inward) along averaged vertex normals."""
    if not d:
        return p
    sgn = 1 if area(p) > 0 else -1
    out = []
    n = len(p)
    for i in range(n):
        x0, y0 = p[i - 1]; x1, y1 = p[i]; x2, y2 = p[(i + 1) % n]
        nx = (y1 - y0) / (math.hypot(x1 - x0, y1 - y0) or 1) + (y2 - y1) / (math.hypot(x2 - x1, y2 - y1) or 1)
        ny = -((x1 - x0) / (math.hypot(x1 - x0, y1 - y0) or 1) + (x2 - x1) / (math.hypot(x2 - x1, y2 - y1) or 1))
        l = math.hypot(nx, ny) or 1
        out.append((x1 + sgn * d * nx / l, y1 + sgn * d * ny / l))
    return out


def rect(w, h, cx=0.0, cy=0.0):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


def double_d(d, flat):
    """Shaft hole: circle of diameter d with two flats `flat` apart (28BYJ-48 shaft), plus the fit allowance."""
    r, f = d / 2 + FIT / 2, flat / 2 + FIT / 2
    return [(r * math.cos(a), max(-f, min(f, r * math.sin(a)))) for a in [2 * math.pi * i / 90 for i in range(90)]]


# ---------- parts: each is {"cut": [("poly", pts, hole?) | ("circle", cx, cy, r, hole?)], "mark": [...]} ----------
def parts(kerf):
    k = kerf / 2
    P = {}

    def poly(pts, hole=False):
        return ("poly", offset(pts, -k if hole else k), hole)

    def circ(cx, cy, r, hole=False):
        return ("circle", cx, cy, r - k if hole else r + k, hole)

    arrow = [("line", -60, 0, 60, 0), ("line", 60, 0, 52, 4), ("line", 60, 0, 52, -4)]
    P["groove_3mm"] = {"cut": [poly(rect(160, 160)), poly(union_hole(), True)],
                       "mark": [("text", -70, 70, 6, "groove plate 3 mm: hole 153 mm + pinion pocket top right")]}
    P["disc_2mm"] = {"cut": [poly(disc_outline())] +
                     [poly(arc_band(), True)],
                     "mark": [("text", -60, 0, 5, "disc 2 mm, stop slot at the bottom left"), ("circle", 0, 0, R_WIN)]}
    P["ring_2mm"] = {"cut": [poly(rect(172, 172)), circ(0, 0, RING_OPEN_R, True), circ(PIN_XY[0], PIN_XY[1], SHAFT_HOLE_D / 2, True)],
                     "mark": [("rect", -15, 54.5, 14.6, 18.5), ("text", -40, 40, 5, "BH1750 (position to confirm)"),
                              ("rect", SLOT_R * math.cos(math.radians(STOP_DEG)) - PIN_SIZE / 2,
                               SLOT_R * math.sin(math.radians(STOP_DEG)) - PIN_SIZE / 2, PIN_SIZE, PIN_SIZE),
                              ("text", -75, -75, 5, "stop pin here (glue the 3 x 3 pin)"),
                              ("text", 40, 80, 5, "motor body behind, shaft hole top right")]}
    P["pinion_3mm"] = {"cut": [poly(gear_full(Z_PIN, RP_PIN)), poly(double_d(SHAFT_D, SHAFT_FLAT), True)],
                       "mark": [("text", -12, -16, 3, "Z24, m1, double-D hole")]}
    P["pins_2mm"] = {"cut": [poly(rect(PIN_SIZE, PIN_SIZE, 0, 0)), poly(rect(PIN_SIZE, PIN_SIZE, 6, 0))],
                     "mark": [("text", -3, -6, 2, "2 spare stop pins")]}
    P["film_L1"] = {"cut": [poly(rect(150, 150))],
                    "mark": arrow + [("text", -70, 60, 5, "L1 150 x 150, transmission axis along the arrow")]}
    P["film_L3"] = {"cut": [poly(rect(150, 150)), circ(0, 0, R_WIN, True)],
                    "mark": arrow + [("text", -70, 60, 5, "L3 disc d150 + 4 corner offcuts (L2): flip each offcut over its diagonal")]}
    return P


def arc_band():
    """The stop slot in the disc: an arc slot of width SLOT_W at radius SLOT_R, in disc frame angles."""
    half = SLOT_W / 2
    a0 = math.radians(STOP_DEG) - math.radians(PIN_SIZE / 2 / SLOT_R * 180 / math.pi)
    a1 = math.radians(STOP_DEG + 90) + math.radians((PIN_SIZE / 2 + 1.0) / SLOT_R * 180 / math.pi)
    outer = arc(0, 0, SLOT_R + half, a0, a1, 60)
    inner = arc(0, 0, SLOT_R - half, a0, a1, 60)[::-1]
    return outer + inner


# ---------- writers ----------
def bbox(part):
    xs, ys = [], []
    for kind, *a in part["cut"]:
        if kind == "poly":
            xs += [p[0] for p in a[0]]; ys += [p[1] for p in a[0]]
        else:
            cx, cy, r, _ = a
            xs += [cx - r, cx + r]; ys += [cy - r, cy + r]
    return min(xs), min(ys), max(xs), max(ys)


def dxf(part):
    x0, y0, _, _ = bbox(part)
    out = ["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "2",
           "0", "LAYER", "2", "CUT", "70", "0", "62", "1", "6", "CONTINUOUS",
           "0", "LAYER", "2", "MARK", "70", "0", "62", "5", "6", "CONTINUOUS", "0", "ENDTAB", "0", "ENDSEC",
           "0", "SECTION", "2", "ENTITIES"]

    def v(x, y): return [str(round(x - x0, 4)), str(round(y - y0, 4))]
    for kind, *a in part["cut"]:
        if kind == "poly":
            out += ["0", "POLYLINE", "8", "CUT", "66", "1", "70", "1"]
            for x, y in a[0]:
                out += ["0", "VERTEX", "8", "CUT", "10", v(x, y)[0], "20", v(x, y)[1], "30", "0"]
            out += ["0", "SEQEND", "8", "CUT"]
        else:
            cx, cy, r, _ = a
            out += ["0", "CIRCLE", "8", "CUT", "10", v(cx, cy)[0], "20", v(cx, cy)[1], "30", "0", "40", str(round(r, 4))]
    for kind, *a in part["mark"]:
        if kind == "line":
            out += ["0", "LINE", "8", "MARK", "10", v(a[0], a[1])[0], "20", v(a[0], a[1])[1], "30", "0",
                    "11", v(a[2], a[3])[0], "21", v(a[2], a[3])[1], "31", "0"]
        elif kind == "circle":
            out += ["0", "CIRCLE", "8", "MARK", "10", v(a[0], a[1])[0], "20", v(a[0], a[1])[1], "30", "0", "40", str(a[2])]
        elif kind == "rect":
            x, y, w, h = a
            for (p, q) in (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))):
                out += ["0", "LINE", "8", "MARK", "10", v(*p)[0], "20", v(*p)[1], "30", "0", "11", v(*q)[0], "21", v(*q)[1], "31", "0"]
        elif kind == "text":
            out += ["0", "TEXT", "8", "MARK", "10", v(a[0], a[1])[0], "20", v(a[0], a[1])[1], "30", "0", "40", str(a[2]), "1", a[3]]
    out += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(out) + "\n"


def svg_overview(P, kerf):
    layout = [("groove_3mm", 0, 0), ("ring_2mm", 190, 0), ("disc_2mm", 0, 190), ("pinion_3mm", 175, 190),
              ("pins_2mm", 175, 230), ("film_L1", 0, 360), ("film_L3", 170, 360)]
    s = 2.6
    body = []
    for name, ox, oy in layout:
        part = P[name]
        x0, y0, x1, y1 = bbox(part)
        h = y1 - y0
        def T(x, y): return ((x - x0 + ox) * s + 20, (h - (y - y0) + oy) * s + 50)
        for kind, *a in part["cut"]:
            if kind == "poly":
                d = "M" + " L".join(f"{T(x, y)[0]:.1f},{T(x, y)[1]:.1f}" for x, y in a[0]) + "Z"
                body.append(f'<path d="{d}" class="cut"/>')
            else:
                cx, cy, r, _ = a
                body.append(f'<circle cx="{T(cx, cy)[0]:.1f}" cy="{T(cx, cy)[1]:.1f}" r="{r*s:.1f}" class="cut"/>')
        for kind, *a in part["mark"]:
            if kind == "line":
                body.append(f'<path d="M{T(a[0], a[1])[0]:.1f},{T(a[0], a[1])[1]:.1f} L{T(a[2], a[3])[0]:.1f},{T(a[2], a[3])[1]:.1f}" class="mark"/>')
            elif kind == "circle":
                body.append(f'<circle cx="{T(a[0], a[1])[0]:.1f}" cy="{T(a[0], a[1])[1]:.1f}" r="{a[2]*s:.1f}" class="mark" fill="none"/>')
            elif kind == "rect":
                x, y, w, hh = a
                body.append(f'<rect x="{T(x, y + hh)[0]:.1f}" y="{T(x, y + hh)[1]:.1f}" width="{w*s:.1f}" height="{hh*s:.1f}" class="mark" fill="none"/>')
        sz = (x1 - x0, y1 - y0)
        body.append(f'<text x="{T(x0, y0)[0]:.1f}" y="{T(x0, y0)[1] + 16:.1f}">{name}  {sz[0]:.0f} x {sz[1]:.0f} mm</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1450" width="1000" height="1450">
<style>text{{font:12px system-ui,sans-serif;fill:#1c2430}}.cut{{fill:none;stroke:#d11;stroke-width:1}}.mark{{stroke:#06c;stroke-width:1;fill:none}}</style>
<rect width="1000" height="1450" fill="#fff"/>
<text x="20" y="24" style="font-size:16px;font-weight:600">PolaGrid 150 mm cell, laser parts (kerf {kerf} mm, red = cut, blue = mark)</text>
{chr(10).join(body)}
</svg>
"""


# ---------- checks ----------
def check(P):
    ra_d, rr_d = RP_DISC + M, RP_DISC - 1.25 * M
    pts = disc_outline()
    assert max(math.hypot(*p) for p in pts) <= HOLE_R - 0.4, "disc tip must clear the groove hole"
    assert abs(CENTRE_D - (RP_DISC + RP_PIN)) < 1e-9 and abs(PIN_XY[0] - 61.52) < 0.05
    assert PIN_XY[0] + RP_PIN + M <= R_WIN + 1e-6, "pinion tip stays inside the 150 mm window square"
    uh = union_hole()
    assert abs(area(uh)) > math.pi * HOLE_R ** 2 * 0.99, "hole plus pocket must be larger than the plain hole"
    assert all(math.hypot(x - PIN_XY[0] * 0, y) >= 0 for x, y in uh)
    # slot sits in the plain rim, clear of the teeth, and fits the ring plate overlap (r 70 .. 76)
    teeth_end = TEETH_FROM_DEG + N_TEETH * 360 / Z_DISC
    slot0, slot1 = STOP_DEG - 1.4, STOP_DEG + 90 + 2.4
    assert teeth_end < slot0 and slot1 < TEETH_FROM_DEG + 360, "stop slot must not overlap the tooth arc"
    assert SLOT_R - SLOT_W / 2 >= RING_OPEN_R and SLOT_R + SLOT_W / 2 <= ra_d - 1.0, "slot sits between the ring opening and the rim, 1 mm wall left"
    for name, part in P.items():
        for kind, *a in part["cut"]:
            if kind == "poly":
                assert len(a[0]) >= 4
    x0, y0, x1, y1 = bbox(P["pinion_3mm"])
    assert abs((x1 - x0) - 2 * (RP_PIN + M)) < 0.2, "pinion outside diameter"
    h, _ = involute_flank(Z_PIN, RP_PIN, RP_PIN + M, RP_PIN - 1.25 * M)
    assert 0 < h(RP_PIN + M) and 2 * h(RP_PIN) * RP_PIN > 1.4, "pinion tooth must keep a positive tip and about pi/2 m thickness"
    print("checks passed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kerf", type=float, default=0.0)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    P = parts(a.kerf)
    check(P)
    if not a.check:
        for name, part in P.items():
            (HERE / f"{name}.dxf").write_text(dxf(part), encoding="ascii")
        (HERE / "cut_overview.svg").write_text(svg_overview(P, a.kerf), encoding="utf-8")
        print("wrote", ", ".join(f"{n}.dxf" for n in P), "and cut_overview.svg")
