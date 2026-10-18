"""Writes cell150.html (front view to scale + stack section) from the numbers in cell150_calc.py."""
import math
from cell150_calc import R, W, r_in, corner_area

# (ko, en); technical terms stay English inside Korean text. Both are emitted, CSS shows one.
TR = {
    "t_front": ("정면도, 150 x 150 mm 셀 (실제 비율)", "Front view, 150 x 150 mm cell (to scale)"),
    "m_front": ("점선 = 앞판 뒤에 있는 부품. 엇갈린 모서리 필름이 네 모서리의 빛을 막는다.", "Dashed = behind the front plate. The crossed corner film blocks light in the four corners."),
    "back": ("back plate 172 x 172 mm", "back plate 172 x 172 mm"),
    "stop": ("disc의 stop slot, pin은 back plate에 고정", "stop slot in the disc, pin on the back plate"),
    "teeth": ("100 deg 호에 teeth 42개", "teeth on a 100 deg arc, 42 teeth"),
    "body": ("28BYJ-48 본체 (plate 뒤쪽)", "28BYJ-48 body (behind the plate)"),
    "pinion": ("pinion", "pinion"),
    "free": ("free circle", "free circle"),
    "win": ("150 mm window = disc 지름", "150 mm window = disc diameter"),
    "t_sec": ("중심과 한 모서리를 지나는 단면", "Section through the centre and one corner"),
    "m_sec": ("왼쪽이 바깥(outdoor). 두께는 과장해서 그렸다.", "Outdoor on the left. Thickness exaggerated."),
    "motor": ("28BYJ-48, 깊이 19 mm", "28BYJ-48, 19 mm deep"),
    "pin_corner": ("모서리의 pinion", "pinion in the corner"),
    "sensor": ("back plate 테두리 위의 cell sensor", "cell sensor on the ring lip"),
    "l1": ("frame glass, 뒷면에 L1 film", "frame glass, L1 film on its back"),
    "l2": ("L2: 모서리 자투리 4장, 뒤집어 붙임", "L2: four corner offcuts, flipped"),
    "l3": ("groove plate, 구멍 153 mm", "groove plate, hole 153 mm"),
    "l4": ("disc: 2 mm acrylic + L3 film, 테두리가 groove에 들어감", "disc 2 mm acrylic + L3 film, rim in the groove"),
    "l5": ("back ring plate, 개구부 140 mm", "back ring plate, opening 140 mm"),
    "h1": ("PolaGrid 150 mm 셀 모듈 (v0.3)", "PolaGrid 150 mm cell module (v0.3)"),
    "sub": ("정면도는 실제 비율, 단면은 두께를 과장했다. 모든 치수는 계산값이고 아직 실측한 것은 없다.", "Front view to scale, stack section with exaggerated thickness. All sizes are calculated, nothing is measured yet."),
    "aria": ("150 mm 셀의 정면도: 테두리에 톱니가 있는 disc, 모서리 pinion, 적층 단면", "Front view of the 150 mm cell with a rim-toothed disc, a corner pinion and a stack section"),
    "title": ("PolaGrid 150 mm 셀", "PolaGrid 150 mm cell"),
}


def L(k):                        # SVG text: both languages, CSS shows one
    ko, en = TR[k]
    return f'<tspan class="ko">{ko}</tspan><tspan class="en">{en}</tspan>'


def LH(ko, en):                  # same, for HTML
    return f'<span class="ko">{ko}</span><span class="en">{en}</span>'


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
  <text class="t" x="40" y="44">{L("t_front")}</text>
  <text class="m" x="40" y="64">{L("m_front")}</text>
  <rect x="{bx0:.1f}" y="{by0:.1f}" width="{172*S:.1f}" height="{172*S:.1f}" class="dash"/>
  <text class="g" x="{bx0+172*S:.1f}" y="{by0+172*S+18:.1f}" text-anchor="end">{L("back")}</text>
  <rect x="{x0:.1f}" y="{y0:.1f}" width="{W*S:.1f}" height="{W*S:.1f}" class="ln" stroke-width="2"/>
  <circle cx="{cx}" cy="{cy}" r="{R*S}" class="f1"/>
  <path d="{corner_fill}" fill-rule="evenodd" class="f2"/>
  <circle cx="{cx}" cy="{cy}" r="{(R+1)*S}" class="gear"/>
  <path d="{sector_ticks(40, 140.8, 42)}" class="tick"/>
  <path d="{slot_path}" class="slot"/>
  <rect x="{pin_xy[0]-1.5*S:.1f}" y="{pin_xy[1]-1.5*S:.1f}" width="{3*S:.1f}" height="{3*S:.1f}" class="pin"/>
  <text class="g" x="{pin_xy[0]+14:.1f}" y="{pin_xy[1]+4:.1f}">{L("stop")}</text>
  <text class="g" x="{cx-110:.1f}" y="{by0+30:.1f}" text-anchor="middle">{L("teeth")}</text>
  <path d="{gear_path(pc, 24, 12)}" class="pin"/>
  <circle cx="{P(*pc)[0]:.1f}" cy="{P(*pc)[1]:.1f}" r="{2.5*S}" class="pin"/>
  <circle cx="{P(*mc)[0]:.1f}" cy="{P(*mc)[1]:.1f}" r="{14*S}" class="srv"/>
  <text class="g" x="{bx0+172*S:.1f}" y="{by0-8:.1f}" text-anchor="end">{L("body")}</text>
  <text class="g" x="{bx0+172*S-30:.1f}" y="{P(*pc)[1]+78:.1f}" text-anchor="middle">Z24</text>
  <text class="g" x="{bx0+172*S-30:.1f}" y="{P(*pc)[1]+92:.1f}" text-anchor="middle">{L("pinion")}</text>
  <circle cx="{icx:.1f}" cy="{icy:.1f}" r="{r_in*S:.1f}" class="dash"/>
  <text class="g" x="{icx:.1f}" y="{icy+4:.1f}" text-anchor="middle">{L("free")}</text>
  <text class="g" x="{icx:.1f}" y="{icy+20:.1f}" text-anchor="middle">d 25.7 mm</text>
  <rect x="{sensx-6*S:.1f}" y="{sensy-2*S:.1f}" width="{14.6*S:.1f}" height="{18.5*S:.1f}" class="sen"/>
  <text class="g" x="{sensx-6*S+14.6*S/2:.1f}" y="{sensy-2*S+18.5*S/2+4:.1f}" text-anchor="middle" style="fill:#fff">BH1750</text>
  <path d="M{x0:.1f},{y0+W*S+26:.1f} h{W*S:.1f} M{x0:.1f},{y0+W*S+18:.1f} v16 M{x0+W*S:.1f},{y0+W*S+18:.1f} v16" class="dim"/>
  <text x="{cx-80:.1f}" y="{by0+172*S+18:.1f}" text-anchor="middle">{L("win")}</text>
'''

# ---- section (thickness 8 px/mm, height 2 px/mm) ----
sx, sy = 860.0, 440.0
T = 8.0
half = 75 * 2
layers = [("glass", 3, "gl"), ("l1", 0.4, "f1"), ("l2", 0.4, "f2"), ("groove", 3, "plate"), ("back", 2, "plate")]
x = sx
sec = [f'<text class="t" x="{sx-60}" y="44">{L("t_sec")}</text>',
       f'<text class="m" x="{sx-60}" y="64">{L("m_sec")}</text>']
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
sec.append(f'<text class="g" x="{bx+bw+10:.1f}" y="{sy-half-70-10:.1f}">{L("motor")}</text>')
sec.append(f'<rect x="{gx+0.4*T:.1f}" y="{sy-half-60:.1f}" width="{1.8*T:.1f}" height="24" class="pin"/>')
sec.append(f'<text class="g" x="{gx-16:.1f}" y="{sy-half-44:.1f}" text-anchor="end">{L("pin_corner")}</text>')
sec.append(f'<rect x="{bx+bw+6:.1f}" y="{sy-8:.1f}" width="10" height="16" class="sen"/>')
sec.append(f'<text class="g" x="{bx+bw+24:.1f}" y="{sy+4:.1f}">{L("sensor")}</text>')
for k, key in enumerate(["l1", "l2", "l3", "l4", "l5"]):
    sec.append(f'<text class="g" x="{sx-60}" y="{sy+half+100+24*k}">{k+1}. {L(key)}</text>')
svg_sec = "\n  ".join(sec)

CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--line:#c9d0d8;--tx:#1c2430;--mut:#3a4656;--acc:#0b7fb5;--warn:#c2410c;--film:#7aa6d6;--film2:#d68a7a;--dark:#2a303a;--ok:#16794c;--gl:#cfe3ee}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#151b23;--line:#2d3744;--tx:#e6ebf1;--mut:#c3cdd9;--acc:#4cc2ff;--warn:#ff9a62;--film:#4f82b8;--film2:#b8685a;--dark:#05070a;--ok:#5ad19a;--gl:#27414f}}
:root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--line:#c9d0d8;--tx:#1c2430;--mut:#3a4656;--acc:#0b7fb5;--warn:#c2410c;--film:#7aa6d6;--film2:#d68a7a;--dark:#2a303a;--ok:#16794c;--gl:#cfe3ee}
:root[data-theme=dark]{--bg:#0d1117;--panel:#151b23;--line:#2d3744;--tx:#e6ebf1;--mut:#c3cdd9;--acc:#4cc2ff;--warn:#ff9a62;--film:#4f82b8;--film2:#b8685a;--dark:#05070a;--ok:#5ad19a;--gl:#27414f}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--tx);font:16px/1.55 system-ui,"Malgun Gothic","Apple SD Gothic Neo",Segoe UI,Roboto,sans-serif;padding:24px 16px}
main{max-width:1240px;margin:0 auto}
h1{font-size:26px;font-weight:700;margin-bottom:4px} p.sub{color:var(--mut);margin-bottom:16px;font-size:16px}
.bar{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
#lang{font:600 15px system-ui,"Malgun Gothic",sans-serif;color:var(--tx);background:var(--panel);border:2px solid var(--acc);border-radius:8px;padding:6px 14px;cursor:pointer;white-space:nowrap}
html[lang=en] .ko,html[lang=ko] .en{display:none}
.wrap{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
svg{width:100%;height:auto;display:block}
text{fill:var(--tx);font-size:16px} .m,.g{fill:var(--mut)} .g{font-size:15px} .t{font-size:19px;font-weight:700}
.ln{stroke:var(--line);fill:none} .dash{stroke:var(--mut);fill:none;stroke-dasharray:5 4}
.f1{fill:var(--film);opacity:.85} .f2{fill:var(--film2);opacity:.85} .plate{fill:var(--dark)} .glass{fill:var(--gl)} .disc{fill:var(--gl);stroke:var(--mut)}
.gear{fill:none;stroke:var(--acc);stroke-width:1.5} .slot{fill:none;stroke:var(--warn);stroke-width:7;opacity:.35} .tick{stroke:var(--acc);stroke-width:1.2;fill:none}
.pin{fill:none;stroke:var(--warn);stroke-width:2} .srv{fill:none;stroke:var(--mut);stroke-width:1.5;stroke-dasharray:4 3}
.sen{fill:var(--ok)} .dim{stroke:var(--mut);fill:none}
.note{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:12px}
.note div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px} .note{word-break:keep-all}
.note b{display:block;margin-bottom:4px;font-size:17px}
"""
NOTES = f"""
  <div><b>{LH("모서리 공간", "Corner space")}</b>{LH(f"disc가 150 x 150 mm window의 78.5 %를 차지한다. 모서리 하나에 {corner_area:.0f} mm2가 남고(네 개 합쳐 21.5 %), 들어가는 가장 큰 free circle은 지름 25.7 mm, 가장 큰 정사각형은 22 mm다. 모서리 필름은 어떤 각도에서도 어둡다.", f"The disc takes 78.5 % of the 150 x 150 mm window. Each corner keeps {corner_area:.0f} mm2 (21.5 % in total). The largest free circle is 25.7 mm across and the largest square 22 mm. Corner film is dark at every angle.")}</div>
  <div><b>{LH("구동", "Drive")}</b>{LH("disc 테두리에 100 deg 호로 teeth 42개(module 1, Z150)가 있다. 한쪽 모서리의 Z24 pinion이 돌리므로 감속비는 6.25다. servo는 180 deg를 돌려도 disc는 28.8 deg뿐이라 90 deg에 못 미친다. 28BYJ-48 stepper는 90 deg에 pinion 1.56바퀴면 되므로 가능하다.", "The disc rim has 42 teeth on a 100 deg arc (module 1, Z150). A Z24 pinion sits in one corner, so the ratio is 6.25. A servo turns 180 deg, which gives the disc 28.8 deg, not 90. A 28BYJ-48 stepper needs 1.56 pinion turns for 90 deg and can do it.")}</div>
  <div><b>{LH("모터 공간", "Motor space")}</b>{LH("28BYJ-48 본체(d 28)는 free circle보다 커서 back plate 뒤에 두고, 본체를 window 가장자리 바로 바깥으로 뺀다. 모서리 안에는 pinion과 shaft만 들어간다.", "The 28BYJ-48 body (d 28) is bigger than the free circle, so it sits behind the back plate with its body just outside the window edge. Only the pinion and its shaft are in the corner.")}</div>
  <div><b>{LH("아직 실측 전", "Not measured yet")}</b>{LH("backlash, groove 안에서 disc의 마찰, 2 mm acrylic disc에서 잃는 빛, 150 mm window 뒤 frame 테두리의 실제 크기.", "Backlash, friction of the disc in the groove, light lost in the 2 mm acrylic disc, and the real size of the frame border behind the 150 mm window.")}</div>
"""
JS = """const d=document.documentElement,TT=%s;
let l=new URLSearchParams(location.search).get('lang');
if(l!='ko'&&l!='en'){l='ko';try{l=localStorage.getItem('lang')==='en'?'en':'ko'}catch(e){}}
function set(x,save){l=x;d.lang=x;document.title=TT[x];document.getElementById('lang').textContent=x=='ko'?'EN':'한국어';
if(save)try{localStorage.setItem('lang',x)}catch(e){}}
set(l,false);document.getElementById('lang').onclick=()=>set(l=='ko'?'en':'ko',true);
const t=new URLSearchParams(location.search).get('theme');if(t)d.dataset.theme=t;""" % ('{ko:"%s",en:"%s"}' % TR["title"])
html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TR["title"][0]}</title>
<style>{CSS}</style></head><body><main>
<div class="bar"><div><h1>{LH(*TR["h1"])}</h1>
<p class="sub">{LH(*TR["sub"])}</p></div><button id="lang" type="button" aria-label="Language">EN</button></div>
<div class="wrap"><svg viewBox="0 0 1240 900" role="img" aria-label="{TR["aria"][0]}">
{svg_front}
  {svg_sec}
</svg></div>
<div class="note">{NOTES}</div>
</main>
<script>{JS}</script></body></html>
"""
open("cell150.html", "w", encoding="utf-8").write(html)
