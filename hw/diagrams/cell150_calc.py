"""Geometry of the 150 x 150 mm cell module (v0.3). Run: python cell150_calc.py  (prints the numbers used in the docs)."""
import math

W = 150.0                       # window (frame opening), mm
R = W / 2                       # disc radius = window half width
corner_area = (W * W - math.pi * R * R) / 4
gap_diag = R * math.sqrt(2) - R                              # corner tip to disc, along the diagonal
r_in = R * (math.sqrt(2) - 1) / (math.sqrt(2) + 1)           # largest circle in a corner (tangent to disc and both sides)
sq = R * (1 - 1 / math.sqrt(2))                              # largest axis-aligned square in a corner


def fits(a, b):                                              # a x b rectangle flush in a corner, outside the disc
    return (R - a) ** 2 + (R - b) ** 2 >= R * R


# gears, module 1: disc rim Z150 (pitch 150), pinion in the corner, centre distance R + rp
m, Zd = 1.0, 150
pin = {}
for Zp in range(12, 40):
    rp = m * Zp / 2
    c = (R + rp) / math.sqrt(2)                              # pinion centre offset per axis from the disc centre
    tip = rp + m
    pin[Zp] = (rp, c, c + tip <= R)                          # tip stays inside the window square
Zmax = max(z for z, v in pin.items() if v[2])
ratio = Zd / Zmax
if __name__ == "__main__":
    print(f"window {W:.0f} x {W:.0f} = {W*W:.0f} mm2, disc {math.pi*R*R:.0f} mm2 ({math.pi*R*R/W/W:.1%})")
    print(f"corners: {corner_area*4:.0f} mm2 in total ({corner_area*4/W/W:.1%}), {corner_area:.0f} mm2 each")
    print(f"gap corner->disc on the diagonal {gap_diag:.1f} mm; largest circle in a corner d={2*r_in:.1f} mm; largest square {sq:.1f} mm")
    for name, a, b in (("SG90 body 22.5 x 12.2", 22.5, 12.2), ("28BYJ-48 body d28 (as 28 x 28)", 28, 28), ("BH1750 GY-302 board 14.6 x 18.5", 14.6, 18.5)):
        print(f"  {name}: fits flush in a corner footprint: {fits(a, b)}")
    print(f"largest pinion in the corner (module 1, tip inside the square): Z{Zmax}, pitch d={Zmax}, centre {pin[Zmax][1]:.1f} mm per axis")
    print(f"ratio {Zd}:{Zmax} = {ratio:.2f}; servo 180 deg -> disc {180/ratio:.1f} deg (need 90)")
    Zp = 24
    rp, c, ok = pin[Zp]
    print(f"chosen pinion Z{Zp}: pitch d {2*rp:.0f}, tip d {2*rp+2*m:.0f}, centre {c:.1f},{c:.1f} mm from the disc centre, tip inside square {ok}; ratio {Zd/Zp:.2f}")
    print(f"disc 90 deg = pinion {90*Zd/Zp:.0f} deg = {90*Zd/Zp/360:.2f} turns; 28BYJ-48 half steps/rev about 4096 -> {90*Zd/Zp/360*4096:.0f} half steps, {360/4096*Zp/Zd:.4f} deg per half step at the disc")
    print(f"teeth on the disc rim: arc about 100 deg = {round(Zd*100/360)} teeth")
