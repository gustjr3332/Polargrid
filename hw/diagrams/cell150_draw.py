"""Writes cell150.html (front view to scale + stack section) from the numbers in cell150_calc.py."""
import math
from cell150_calc import R, W, r_in, corner_area

S = 4.0                       # px per mm in the front view
cx, cy = 380.0, 440.0


def P(x, y):                  # mm from the disc centre (x right, y up) -> px
    return cx + x * S, cy - y * S


def gear_path(zc, z, rp, m=1.0):                               # simple trapezoid teeth
    pts = []
    for i in range(z):
        for dr, f in ((-1.25, 0.0), (-1.25, 0.28), (1.0, 0.38), (1.0, 0.62), (-1.25, 0.72)):
            a = (i + f) * 2 * math.pi / z
            r = rp + dr * m
            pts.append(P(zc[0] + r * math.cos(a), zc[1] + r * math.sin(a)))
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"


def sector_ticks(a1, a2, n):
    out = []
    for i in range(n + 1):
        a = math.radians(a1 + (a2 - a1) * i / n)
        x1, y1 = P((R - 1.25) * math.cos(a), (R - 1.25) * math.sin(a))
        x2, y2 = P((R + 1) * math.cos(a), (R + 1) * math.sin(a))
        out.append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}")
    return " ".join(out)


pc = (61.5, 61.5)                                              # pinion centre (top right corner)
mc = (pc[0] + 8, pc[1])                                        # 28BYJ-48 body centre: the shaft is 8 mm off the body centre
x0, y0 = P(-R, R)
corner_fill = (f"M{x0:.1f},{y0:.1f} h{W*S:.1f} v{W*S:.1f} h{-W*S:.1f} Z "
               f"M{cx+R*S:.1f},{cy:.1f} A{R*S:.1f},{R*S:.1f} 0 1 0 {cx-R*S:.1f},{cy:.1f} "
               f"A{R*S:.1f},{R*S:.1f} 0 1 0 {cx+R*S:.1f},{cy:.1f} Z")
slot_pts = [P(72 * math.cos(math.radians(a)), 72 * math.sin(math.radians(a))) for a in [223.8 + (317.0 - 223.8) * i / 40 for i in range(41)]]
slot_path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in slot_pts)
pin_xy = P(72 * math.cos(math.radians(225)), 72 * math.sin(math.radians(225)))
icx, icy = P(-(R - r_in), -(R - r_in))                         # free circle, bottom left corner
bx0, by0 = P(-86, 86)
sensx, sensy = P(-9, 71)

svg_front = f'''
  <text class="t" x="40" y="44">Front view, 150 x 150 mm cell (to scale)</text>
  <text class="m" x="40" y="64">Dashed = behind the front plate. The crossed corner film blocks light in the four corners.</text>
  <rect x="{bx0:.1f}" y="{by0:.1f}" width="{172*S:.1f}" height="{172*S:.1f}" class="dash"/>
  <text class="g" x="{bx0+172*S:.1f}" y="{by0+172*S+18:.1f}" text-anchor="end">back plate 172 x 172 mm</text>
  <rect x="{x0:.1f}" y="{y0:.1f}" width="{W*S:.1f}" height="{W*S:.1f}" class="ln" stroke-width="2"/>
  <circle cx="{cx}" cy="{cy}" r="{R*S}" class="f1"/>
  <path d="{corner_fill}" fill-rule="evenodd" class="f2"/>
  <circle cx="{cx}" cy="{cy}" r="{(R+1)*S}" class="gear"/>
  <path d="{sector_ticks(40, 140.8, 42)}" class="tick"/>
  <path d="{slot_path}" class="slot"/>
  <rect x="{pin_xy[0]-1.5*S:.1f}" y="{pin_xy[1]-1.5*S:.1f}" width="{3*S:.1f}" height="{3*S:.1f}" class="pin"/>
  <text class="g" x="{pin_xy[0]+14:.1f}" y="{pin_xy[1]+4:.1f}">stop slot in the disc, pin on the back plate</text>
  <text class="g" x="{cx-110:.1f}" y="{by0+30:.1f}" text-anchor="middle">teeth on a 100 deg arc, 42 teeth</text>
  <path d="{gear_path(pc, 24, 12)}" class="pin"/>
  <circle cx="{P(*pc)[0]:.1f}" cy="{P(*pc)[1]:.1f}" r="{2.5*S}" class="pin"/>
  <circle cx="{P(*mc)[0]:.1f}" cy="{P(*mc)[1]:.1f}" r="{14*S}" class="srv"/>
  <text class="g" x="{bx0+172*S:.1f}" y="{by0-8:.1f}" text-anchor="end">28BYJ-48 body (behind the plate)</text>
  <text class="g" x="{bx0+172*S-30:.1f}" y="{P(*pc)[1]+78:.1f}" text-anchor="middle">Z24</text>
  <text class="g" x="{bx0+172*S-30:.1f}" y="{P(*pc)[1]+92:.1f}" text-anchor="middle">pinion</text>
  <circle cx="{icx:.1f}" cy="{icy:.1f}" r="{r_in*S:.1f}" class="dash"/>
  <text class="g" x="{icx:.1f}" y="{icy+4:.1f}" text-anchor="middle">free circle</text>
  <text class="g" x="{icx:.1f}" y="{icy+20:.1f}" text-anchor="middle">d 25.7 mm</text>
  <rect x="{sensx-6*S:.1f}" y="{sensy-2*S:.1f}" width="{14.6*S:.1f}" height="{18.5*S:.1f}" class="sen"/>
  <text class="g" x="{sensx-6*S+14.6*S/2:.1f}" y="{sensy-2*S+18.5*S/2+4:.1f}" text-anchor="middle" style="fill:#fff">BH1750</text>
  <path d="M{x0:.1f},{y0+W*S+26:.1f} h{W*S:.1f} M{x0:.1f},{y0+W*S+18:.1f} v16 M{x0+W*S:.1f},{y0+W*S+18:.1f} v16" class="dim"/>
  <text x="{cx-80:.1f}" y="{by0+172*S+18:.1f}" text-anchor="middle">150 mm window = disc diameter</text>
'''

# ---- section (thickness 8 px/mm, height 2 px/mm) ----
sx, sy = 860.0, 440.0
T = 8.0
half = 75 * 2
layers = [("glass", 3, "gl"), ("l1", 0.4, "f1"), ("l2", 0.4, "f2"), ("groove", 3, "plate"), ("back", 2, "plate")]
x = sx
sec = [f'<text class="t" x="{sx-60}" y="44">Section through the centre and one corner</text>',
       f'<text class="m" x="{sx-60}" y="64">Outdoor on the left. Thickness exaggerated.</text>']
pos = {}
for name, th, cls in layers:
    w = th * T
    pos[name] = (x, w)
    if cls == "plate":
        sec.append(f'<rect x="{x:.1f}" y="{sy-half-70:.1f}" width="{w:.1f}" height="70" class="plate"/>')
        sec.append(f'<rect x="{x:.1f}" y="{sy+half:.1f}" width="{w:.1f}" height="70" class="plate"/>')
    elif cls == "gl":
        sec.append(f'<rect x="{x:.1f}" y="{sy-half-70:.1f}" width="{w:.1f}" height="{2*half+140:.1f}" class="glass"/>')
    else:
        sec.append(f'<rect x="{x:.1f}" y="{sy-half:.1f}" width="{w:.1f}" height="{2*half:.1f}" class="{cls}"/>')
    x += w
gx, gw = pos["groove"]
sec.append(f'<rect x="{gx+0.5*T:.1f}" y="{sy-half:.1f}" width="{2*T:.1f}" height="{2*half:.1f}" class="disc"/>')
sec.append(f'<rect x="{gx+2.5*T:.1f}" y="{sy-half:.1f}" width="{0.4*T:.1f}" height="{2*half:.1f}" class="f1"/>')
bx, bw = pos["back"]
sec.append(f'<rect x="{bx+bw:.1f}" y="{sy-half-70:.1f}" width="{19*T:.1f}" height="56" class="srv"/>')
sec.append(f'<text class="g" x="{bx+bw+10:.1f}" y="{sy-half-70+32:.1f}">28BYJ-48, 19 mm deep</text>')
sec.append(f'<rect x="{gx+0.4*T:.1f}" y="{sy-half-60:.1f}" width="{1.8*T:.1f}" height="24" class="pin"/>')
sec.append(f'<text class="g" x="{gx-8:.1f}" y="{sy-half-44:.1f}" text-anchor="end">pinion in the corner</text>')
sec.append(f'<rect x="{bx+bw+6:.1f}" y="{sy-8:.1f}" width="10" height="16" class="sen"/>')
sec.append(f'<text class="g" x="{bx+bw+24:.1f}" y="{sy+4:.1f}">cell sensor on the ring lip</text>')
for k, t in enumerate(["frame glass, L1 film on its back", "L2: four corner offcuts, flipped",
                       "groove plate, hole 153 mm", "disc 2 mm acrylic + L3 film, rim in the groove",
                       "back ring plate, opening 140 mm"]):
    sec.append(f'<text class="g" x="{sx-60}" y="{sy+half+100+20*k}">{k+1}. {t}</text>')
svg_sec = "\n  ".join(sec)

CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--line:#c9d0d8;--tx:#1c2430;--mut:#5d6b7a;--acc:#0b7fb5;--warn:#c2410c;--film:#7aa6d6;--film2:#d68a7a;--dark:#2a303a;--ok:#16794c;--gl:#cfe3ee}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#151b23;--line:#2d3744;--tx:#e6ebf1;--mut:#93a1b1;--acc:#4cc2ff;--warn:#ff9a62;--film:#4f82b8;--film2:#b8685a;--dark:#05070a;--ok:#5ad19a;--gl:#27414f}}
:root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--line:#c9d0d8;--tx:#1c2430;--mut:#5d6b7a;--acc:#0b7fb5;--warn:#c2410c;--film:#7aa6d6;--film2:#d68a7a;--dark:#2a303a;--ok:#16794c;--gl:#cfe3ee}
:root[data-theme=dark]{--bg:#0d1117;--panel:#151b23;--line:#2d3744;--tx:#e6ebf1;--mut:#93a1b1;--acc:#4cc2ff;--warn:#ff9a62;--film:#4f82b8;--film2:#b8685a;--dark:#05070a;--ok:#5ad19a;--gl:#27414f}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;padding:24px 16px}
main{max-width:1240px;margin:0 auto}
h1{font-size:22px;font-weight:600;margin-bottom:4px} p.sub{color:var(--mut);margin-bottom:16px}
.wrap{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
svg{width:100%;height:auto;display:block}
text{fill:var(--tx);font-size:13px} .m,.g{fill:var(--mut)} .g{font-size:12px} .t{font-size:15px;font-weight:600}
.ln{stroke:var(--line);fill:none} .dash{stroke:var(--mut);fill:none;stroke-dasharray:5 4}
.f1{fill:var(--film);opacity:.85} .f2{fill:var(--film2);opacity:.85} .plate{fill:var(--dark)} .glass{fill:var(--gl)} .disc{fill:var(--gl);stroke:var(--mut)}
.gear{fill:none;stroke:var(--acc);stroke-width:1.5} .slot{fill:none;stroke:var(--warn);stroke-width:7;opacity:.35} .tick{stroke:var(--acc);stroke-width:1.2;fill:none}
.pin{fill:none;stroke:var(--warn);stroke-width:2} .srv{fill:none;stroke:var(--mut);stroke-width:1.5;stroke-dasharray:4 3}
.sen{fill:var(--ok)} .dim{stroke:var(--mut);fill:none}
.note{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:12px}
.note div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px} .note b{display:block;margin-bottom:4px}
"""
NOTES = f"""
  <div><b>Corner space</b>The disc takes 78.5 % of the 150 x 150 mm window. Each corner keeps {corner_area:.0f} mm2 (21.5 % in total). The largest free circle is 25.7 mm across and the largest square 22 mm. Corner film is dark at every angle.</div>
  <div><b>Drive</b>The disc rim has 42 teeth on a 100 deg arc (module 1, Z150). A Z24 pinion sits in one corner, so the ratio is 6.25. A servo turns 180 deg, which gives the disc 28.8 deg, not 90. A 28BYJ-48 stepper needs 1.56 pinion turns for 90 deg and can do it.</div>
  <div><b>Motor space</b>The 28BYJ-48 body (d 28) is bigger than the free circle, so it sits behind the back plate with its body just outside the window edge. Only the pinion and its shaft are in the corner.</div>
  <div><b>Not measured yet</b>Backlash, friction of the disc in the groove, light lost in the 2 mm acrylic disc, and the real size of the frame border behind the 150 mm window.</div>
"""
html = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>PolaGrid 150 mm cell</title>\n<style>{CSS}</style></head><body><main>\n'
        '<h1>PolaGrid 150 mm cell module (v0.3)</h1>\n'
        '<p class="sub">Front view to scale, stack section with exaggerated thickness. All sizes are calculated, nothing is measured yet.</p>\n'
        '<div class="wrap"><svg viewBox="0 0 1240 900" role="img" aria-label="Front view of the 150 mm cell with a rim-toothed disc, a corner pinion and a stack section">\n'
        f'{svg_front}\n  {svg_sec}\n</svg></div>\n<div class="note">{NOTES}</div>\n</main>\n'
        "<script>const t=new URLSearchParams(location.search).get('theme');if(t)document.documentElement.dataset.theme=t;</script></body></html>\n")
open("cell150.html", "w", encoding="utf-8").write(html)
