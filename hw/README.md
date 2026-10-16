# hw
Hardware: circuits, parts (BOM), and mechanical design for the polarizer window cells.

## Cell design v1 (corner filler)
Demo panel: 4 cells (2 x 2), 30 x 30 mm window per cell. A square window with a rotating polarizer cannot be covered
corner to corner by a rotating square, so the rotating film is a disc and the corners are filled with fixed film.

Layers, outdoor side to room side:

| Layer | Piece | Axis | Moves |
|---|---|---|---|
| L1 | 30 x 30 mm film, glued to the window plate | 0 deg (reference) | no |
| L2 | 30 x 30 mm scrap film with a 28 mm hole punched in the middle, laminated on 0.5 mm clear acrylic | 90 deg (square piece turned 90 deg) | no |
| L3 | 30 mm disc of film | theta, 0 to 90 deg relative to L1 | yes, servo |

- L2 is crossed with L1, so the four corners stay dark at every angle. No black mask is needed and the window looks like
  one film.
- The 1 mm ring left around the hole stays dark too (L2 crossed with L1), so the open area is the 28 mm circle: 616 of 900
  mm2, 68 %.
- The disc stays larger than the hole at every angle, so no light bypasses it.
- Transmission is about T_single^2 x cos^2(theta) between L1 and L3 (Malus). Measure it with the 10-point test before
  trusting any number.
- Film per cell: 3 pieces cut on a 30 mm grid. 4 cells = 12 pieces, plus about 6 spare for the angle-vs-lux test and
  cutting mistakes. One 300 x 200 mm sheet gives 60.
- Mark the transmission axis on the sheet before cutting, and check it by laying two pieces at 90 deg (dark) and 0 deg
  (clear).

## Drive (option B: pinion in the frame beside the cell)
The film disc is glued on a clear acrylic carrier gear. A small pinion in the frame next to the cell turns it, and the
servo sits behind the plate under the pinion. No hub or gear touches the window.

| Part | Spec | Per cell |
|---|---|---|
| Carrier gear | clear acrylic 2 mm, module 1, 30 teeth (pitch 30 mm, tip 32 mm); L3 film disc glued on its face | 1 |
| Pinion | module 1, 15 teeth (pitch 15 mm, tip 17 mm), fixed to the servo horn | 1 |
| Servo | SG90 class (about 23 x 12 mm body) | 1 |
| Gear plate | acrylic 2 mm, bore 32.4 mm for the carrier gear, slot for the pinion | shared |
| Front plate | opaque, 30 x 30 mm opening, holds L1 and L2 | shared |

- Centre distance 22.5 mm. Ratio 2:1, so the 180 deg servo turns the disc 90 deg (the disc turns the opposite way).
  Disc angle = servo angle / 2, up to the sign and offset found by calibration.
- A gear instead of a rubber roller means no slip, so the angle does not drift and no homing run is needed.
- Layer order: L1, L2 (a 0.3 mm air gap behind it), L3 film on the carrier gear. The pinion is as thick as the gear, so it
  never touches the film.
- Frame: each cell needs about 33 mm from its centre to the outer edge on the pinion side, and 34.4 mm between the centres
  of neighbouring cells (bores 32.4 mm plus a 2 mm wall). The 2 x 2 panel is about 100 x 100 mm. Put the pinions on the
  outer sides (left column left, right column right, top row top, bottom row bottom) so no pinion sits between two cells.
- The windows are 4.4 mm apart (opaque wall). This is the price of option B.
- Laser cutting: the gear teeth need the kerf (about 0.1 to 0.2 mm) added to the drawing. Cut a test pair and check the
  backlash before cutting four.

Not measured yet: backlash and angle resolution of the gear pair (a servo with about 1 deg dead band gives about 0.5 deg
at the disc), and the light lost in the 2 mm acrylic carrier. Both go into the 10-point test.
