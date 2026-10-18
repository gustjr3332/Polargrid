# hw
Hardware: circuits, parts (BOM), and mechanical design for the polarizer window cell.

## Product concept
One central control module plus control modules sold one cell at a time. A control module is a square cell the user sticks
on the window; the user buys as many as the window needs. The 11/4 demo hardware is one central module and one control
module, built into a 15 x 15 cm picture frame that stands in for the window (the 150 x 150 mm glass area is one cell).

## Cell design v0.3 (150 mm cell, rim-toothed disc)
Drawing: `diagrams/cell150.html` (front view to scale, stack section). Numbers: `diagrams/cell150_calc.py`. Everything
below is calculated, nothing is measured.

A rotating polarizer disc of 150 mm diameter sits in a 150 x 150 mm window. The four corners left over (1,207 mm2 each,
21.5 % of the window in total) are covered by fixed film crossed with the front film, so they stay dark at every angle.

Layers, outdoor side to room side:

| Layer | Piece | Axis | Moves |
|---|---|---|---|
| Front | frame glass with L1 film on its back, 150 x 150 mm | 0 deg (reference) | no |
| L2 | the four corner offcuts left when the L3 disc is cut, flipped over (flipping about the diagonal turns the axis by 90 deg) | 90 deg | no |
| Groove plate | clear acrylic 3 mm, 153 mm hole for the disc, a pocket for the pinion in one corner | | no |
| L3 | disc of film, 150 mm, on a 2 mm clear acrylic disc of 152 mm | theta, 0 to 90 deg relative to L1 | yes |
| Back ring plate | clear acrylic 2 mm, 172 x 172 mm, 140 mm opening; holds the disc by its rim, carries the motor and the cell sensor | | no |

- Layers are glued (acrylic cement, hot glue), no bolts or nuts.
- Transmission is about T_single^2 x cos^2(theta) between L1 and L3 (Malus). Measure it with the 10-point test before
  trusting any number.
- Mark the transmission axis on the sheet before cutting and check it by laying two pieces at 90 deg (dark) and 0 deg
  (clear). Test the laser cutter and the adhesive on a scrap piece of film first.

## Drive
The disc has module 1 teeth (Z150) on a 100 deg arc of its rim, 42 teeth. A Z24 pinion sits in one corner and turns it:
ratio 6.25:1. The pinion centre is 61.5 mm from the disc centre along each axis, and its tip stays inside the window
square. The free space in a corner is a circle of 25.7 mm and a square of 22 mm.

- A servo does not work here: 180 deg at the pinion is only 28.8 deg at the disc. A 2:1 ratio would need a 75 mm
  pinion, which does not fit in the corner.
- A 28BYJ-48 stepper (about 4,096 half steps per turn, typical value) turns the pinion 1.56 turns for 90 deg at the
  disc, about 0.014 deg per half step. Its body (d 28 mm) does not fit in the corner, so it sits behind the back plate
  with the body pushed outside the window edge by its 8 mm shaft offset. The frame border behind the window has to leave
  room for it (not checked).
- Home: the disc has an arc slot (3.6 mm wide, about 93 deg) and a 3 x 3 mm pin glued on the back plate sits in it. At power-up the firmware drives the disc 100 deg back until the pin touches the slot end and calls that 0 deg; the other end of the slot is the 90 deg limit.
- Laser drawings (DXF) and the script that makes them: `cutting/` (`cell150_cut.py`, preview `cut_overview.png`). Kerf and tooth backlash are defaults, not tested on the real machine.
- Not measured yet: backlash, friction of the disc in the groove, light lost in the 2 mm acrylic disc, and whether
  the 1 mm of play between a 3 mm groove plate and a 2 mm disc needs a foam shim.
