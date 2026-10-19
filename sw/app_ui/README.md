# app_ui: PolaGrid Android app (draft v0)

The app shows the window's cells and the desk light, and lets the user correct the AI. It talks to the oneM2M CSE
only. It never talks to the cells or the AI controller directly, so the same app works for 12 real cells or 1,000
virtual ones.

## Scope

In v0: see the window, change the mode, say "too bright / too dark", move a single cell by hand, see today's numbers.
Out of v0: accounts, multiple windows, push notifications, anything that needs a number we have not measured.

## Screens

1. **Window** (home). The cell grid (3 x 4 for the demo window), each cell filled by its open level (`cod:opeLl`, 0 to
   100). Below it the desk light per desk in lux, the mode chip, and a connection badge. Tap a cell for manual control.
2. **Comfort**. Two big buttons, "Too bright" and "Too dark", plus a slider for how much (about 100 to 500 lux). Each
   press is one correction: it is sent to the controller and also kept as a training sample for the AI (3) preference model.
3. **Mode**. Auto, Manual, Privacy (all cells closed at night), Away (all open). Auto is the default. Manual keeps the
   AI out until the user switches back or the timer ends.
4. **Today**. Measured values only: glare hours, hours the desk was below target, number of corrections, servo moves.
   No savings figures until we have measured ones (project rule).
5. **Settings**. CSE address, originator, connection test, language, safe-state explanation.

Manual cell control: one cell, an angle slider, and "Open all" / "Close all". An unreachable CSE never leaves cells
closed: cells return to the open state on their own (project safety rule), and the app shows that state.

## Data flow (oneM2M)

| App action | Resource | Operation |
|---|---|---|
| Read cell levels | cell `state` FlexContainer (`cod:opeLl`), found by label `polagrid/<run>/state` | discovery (`fu=1`), then GET |
| Read desk light, sun | `env/desks`, `env/sun` containers | GET `/la` every 3 s (v0), subscription later |
| Mode, correction, manual cell | new container `ctl/app` (CIN with `{type, ...}`) | POST CIN |

The controller subscribes to `ctl/app` and applies the request. This needs two things on the CSE side that do not
exist yet: the `ctl/app` container and an ACP for a new originator `C<run>app` with read on state, desks and sun, and
create on `ctl/app` only. The existing viewer role (read and discover only) is the base.

## Stack

Kotlin, Jetpack Compose, OkHttp for the oneM2M HTTP binding, kotlinx.serialization. v0 polls; the MQTT binding is a
later step (it also serves the protocol-diversity item of the contest rubric). UI text is Korean or English (see "Language toggle").

## Design (Figma)

Frames to draw first: Window (3 states: auto, manual, offline), Comfort, Mode, Today, Settings, cell sheet.
Tokens: one accent color for "open light", neutral grays for the rest, glare shown by a warm tint on the affected
cells. Cell fill encodes open level; do not use color alone (add the number on tap).

## Open questions

- Which phone and Android version the demo uses (decides the minimum SDK).
- Whether the demo phone reaches the CSE directly (same Wi-Fi, port forward) or through the IN.
- Does the app write the correction as an absolute offset in lux or as a +/- step.

## Screen mockup (for the 11/4 slide)

`mockup/index.html` is a static HTML mockup of the five screens in a phone frame, with made-up numbers labelled "DEMO DATA".
It is only captured for one slide, so the app does not have to run on Android and no Android Studio is needed. Open it in
Chrome: `?s=0..4` shows one screen (0 Window, 1 Comfort, 2 Mode, 3 Today, 4 Settings), `?view=all` shows all five. The Mode
screen puts the three goals from the proposal (reduce desk glare, reduce screen reflection, brightest) under Auto.
**Status 2026-10-19: app development is finished (decision of the project owner).** The only work left is to connect the real cell after it is built (10/24) and check it the week after: see "Live real cell" below. A real Kotlin/Compose app is after 11/4.

**Live real cell (2026-10-19).** `?live=1` makes the Window screen show the one real cell: its open level, desk lux and cell-sensor lux,
read every 2 s from `/api/real` of `demo/server.py` (viewer GETs only). Serve it from that server, with `--real RUN`, in WSL:
`python3 server.py --live --mns 1 --real real1` (or `--replay FILE --real real1`), then open `http://localhost:8000/mockup/?live=1`.
Start `tools/fake_cell.py --run real1` first to try it without hardware (the page then says "FAKE CELL"). Checked with a stub CSE
and a headless screenshot, not yet with tinyIoT or the ESP32. Mode, goal, brightness slider and the other four screens are still
made-up, and the Mode/Comfort buttons do not send anything.

**Phone install as PWA (2026-10-19).** The mockup has a manifest and an apple-touch-icon, so Safari on an iPhone can add it to the home
screen (Share, Add to Home Screen) and it opens full screen. Open `http://<PC IP>:8000/mockup/?live=1` from the phone on the same Wi-Fi first
(WSL needs a port proxy to the PC's IP). Checked 2026-10-19 in WSL with tinyIoT (IN first, then MN 1) and `fake_cell.py`: `/api/real` followed `real_cell.py manual 45 90 0` as level 100, 50, 0, 100, and Windows `localhost:8000` reached it. The MN exits at start if the IN on port 3000 is not up. On the live Window screen you touch a cell and drag the top edge of its yellow part up or down (steps of 5 %); letting go sends that cell's open level (0 to 100) to `/api/real/level` (`{level, i}`, no `i` = every cell; the "Open all" / "Close all" buttons use that). `server.py` forwards it to `tools/real_cell.py --run real1 app` (127.0.0.1:9600), which posts one command CIN into `{run}p<i>/command` as the controller, so a cell that was added later works at once (no command group); a dashed line and "level → target" show the target until the cell arrives (or 45 s). Start `real_cell.py app` next to the server. This is a stopgap, not the `ctl/app` container planned above, and the endpoint has no login, so use it on a trusted Wi-Fi only. Checked with fake_cell: POST 30 gave level 30 after about 8 s, a screenshot showed the slider, a headless Chrome run that fires the slider events moved the cell 10 to 80 to 20 after about 9 s (an earlier build never sent the command: `API` was undefined). On the live Comfort screen "Too bright" / "Too dark" (size 100 to 500 lux) POST `/api/real/correction`, and `server.py` stores one row in `demo/corrections.db` (SQLite, git-ignored): time (KST), kind, size, wanted offset (negative = too bright, as in `polagrid/prefs.py`), cell open level, desk and cell lux, and `fake` = 1 when the cell is `fake_cell.py`. `GET /api/real/corrections` returns the count and last 5. The controller does not use the fitted model yet. `python3 tools/fit_corrections.py` (in `sw/edge_ai`) reads the table, rebuilds `ai.features()` from each timestamp (clear-sky outdoor light, since the real cell has no outdoor sensor) and fits `ai.fit_preference`; fake rows are skipped unless `--include-fake`, and that model file is named `preference_FAKE`. Phone access: `demo/phone_proxy.ps1` in an admin PowerShell forwards Windows port 8000 to WSL and opens the firewall for the local subnet (`-Remove` undoes it). **Rooms on the demo page (2026-10-19).** `demo/static/index.html` now draws the 1,000 cells as ten 10 x 10 rooms (5 across, 2 down, "방 1" to "방 10", row 0 at the bottom as in `physics.py`) when the frames come from a server (live or replay). Before, the flat list was laid out 40 cells per line, which cut every room into pieces. The built-in demo generator (no server) keeps the flat grid. Checked on the 10-17 recording at 1,920 x 1,080: every room shows one dark patch where the sun lands, the same shape in all rooms because the ten zones run the same model and sun.

**Access token (2026-10-19).** `demo/server.py --token T` (or `DEMO_TOKEN`) makes every POST need the header `X-Demo-Token`; the pages read `?token=...` from their address and keep it in localStorage. `demo/demo_up.sh` generates one per start and prints the links. Details in `demo/README.md`.

**Layout polish (2026-10-19).** With `?bare` (phone) the page fills the screen height (`100dvh`) and the body scrolls, so nothing is cut off on a short phone; the "live / fake cell" badge moved from the bottom to the header, cells in a 2-column grid are wider than tall, and the glare legend is hidden on the live screen. Checked in headless Chrome at 390 x 844, 2x.

**Select cells, one slider for all of them (2026-10-19).** The "Select cells" chip on the live Window screen turns tapping into picking: tap cells to tick them (all are ticked when the mode is switched on; "Select all" / "Clear" toggles), and the slider under it sets the open level of the ticked cells at once. The page POSTs `{"level", "cells": [indexes]}` to `/api/real/level` and `real_cell.py app` sends each listed cell its own command (a single `i`, or no list = every cell, still work). With select mode off, touching a cell and dragging its edge sets that one cell. Checked with four fake cells: ticking 0 and 3 and moving the slider to 40 set cells 0 and 3 to 40 after about 10 s and left cells 1 and 2 at 100.

**Cells appear one by one, where they were installed.** Each cell firmware has `CELL_INDEX`, `CELL_ROW`, `CELL_COL` in `secrets.h` (row 0 = top, col 0 = left, seen from inside the room). It puts the position on its `state` as a second label `polagrid/<run>/pos/<row>/<col>`. `/api/real` finds the cells by the state label (cached 3 s), reads each position and level, and returns `cells`; the Window screen draws one box per cell at its row and column, dashed boxes for empty places, and a new cell pops in. Checked with `fake_cell.py --index 1 --row 0 --col 1` etc. (four cells in a 2 x 2 grid, the fourth appeared within a few seconds of starting it). Not done: a cell cannot be removed from the screen except by deleting its resources on the CSE. While the disc turns the cell shows "Moving, target N%". The status bar has a Wi-Fi icon (struck out when the cell cannot be read) because the phone must be on the same Wi-Fi as the cell module. It reads `/api/real` from the same server, so there is no API address setting. Not tried on a phone.
An Android app via Capacitor was scaffolded and removed the same day (the SDK alone was about 7 GB and the demo phone is an iPhone).
