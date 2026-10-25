# hw
Hardware: circuits, parts (BOM), and mechanical design for the polarizer window cell.

## Product concept
One central control module plus control modules sold one cell at a time. A control module is a square cell the user sticks
on the window; the user buys as many as the window needs. The 11/4 demo hardware is one central module and one control
module, built into a picture frame that stands in for the window (the frame's inner glass area is one cell).

## Cell design v0.4 (10-22: round acrylic disc, timing belt, no laser cutting)
Everything below is calculated or read from the order list, nothing is measured. The 150 mm design (v0.3, laser-cut disc and
groove plate, drawings in `diagrams/cell150.html` and `cutting/`) is no longer built; those files are kept as history only.

Ordered parts that fix the geometry:

| Part | Value |
|---|---|
| Round acrylic disc | O179 mm |
| Picture frame | square, 178 mm inner width |
| Timing pulley | MISUMI C-ATP40MXL019-B-P5, 40 teeth, MXL (2.032 mm pitch), pitch diameter 25.9 mm |
| Timing belt | BANDO 76MXL3.2, 76 teeth, 3.2 mm wide, about 154 mm long |
| Motor | 28BYJ-48 with ULN2003 driver (already owned) |
| Film | polarizing film, size and cutting plan not decided yet |

- The disc (179 mm) is 1 mm larger than the frame opening (178 mm). This works because the frame widens toward the back,
  so the disc seats behind the narrow front opening and the visible area is the 178 mm opening.
- The belt is a closed loop. Cut it open and glue the strip teeth-outward on the disc rim. At a belt pitch radius of about
  90.4 mm (disc radius 89.5 mm plus an estimated 0.9 mm), 154 mm covers an arc of about 98 deg, enough for the 90 deg stroke
  plus a few degrees of margin.
- Drive ratio is belt pitch radius over pulley pitch radius: 90.4 / 12.94, about 6.99. With 4,096 half steps per motor turn
  that is about 79 half steps per degree of disc (`STEPS_PER_DISC_DEG` in `sw/actuator/src/cell_logic.h`). The 0.9 mm and
  the 4,096 are estimates; calibrate both with the 10-point test.
- Pulley position: centre distance is about 103.3 mm (belt pitch radius plus pulley pitch radius), so along each axis the
  pulley sits near 73 mm from the disc centre, inside a square corner whose half width is 89 mm. The pulley flange diameter
  is not in the order list; check that it stays under about 32 mm, or the pulley will touch the frame wall.
- A servo does not work here: 180 deg at the pulley is only about 26 deg at the disc.
- Layers are glued or taped, no laser cutting. The stack order (L1 film on the front glass, L3 film on the disc, fixed L2
  crossed film in the corners) from v0.3 still applies in principle, but the corner offcut plan depended on a 150 mm disc
  in a 150 mm window and has to be redone for a round 179 mm disc in a 178 mm square. Not decided.
- Transmission is about T_single^2 x cos^2(theta) between L1 and L3 (Malus). Measure it with the 10-point test before
  trusting any number.
- Mark the transmission axis on the sheet and check it by laying two pieces at 90 deg (dark) and 0 deg (clear).
- Home: the firmware drives the disc 100 deg back until a stop touches, and calls that 0 deg. The stop design is not
  decided for the round disc (v0.3 used an arc slot and a pin).
- Not measured yet: belt slip and backlash, friction of the disc against the frame, light lost in the acrylic disc, and where
  the motor body goes (its 28 mm body does not fit in the corner next to the pulley).

Korean versions (for the 11/4 school demo): the wiring diagram is `diagrams/wiring.ko.html` (source
`wiring.architecture.ko.json`); the English `wiring.html` is unchanged. `diagrams/cell150.html` still shows the old 150 mm
cell.
