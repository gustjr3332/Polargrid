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
later step (it also serves the protocol-diversity item of the contest rubric). UI text is English only.

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
A real Kotlin/Compose app is after 11/4.

## Demo page (for the 11/4 maker contest)

A separate web page shows 1,000 virtual cells (the real 4-cell panel is demonstrated separately, not on this page). It is a viewer, so like the app it reads
the CSE only. Plan and phases: `docs/PolaGrid_시연페이지_계획.md` (Korean, local only).

Status 2026-10-15: phase P0 is done. `demo/static/index.html` is one file with no libraries and draws a 25 x 40 grid on a
canvas from generated frames, so the numbers on it are fake and the page says "DEMO DATA". It was checked by eye at
1920 x 1080 (grid fills the panel, Start/Stop and the Cloud event work). Smoothness at 5 frames per second is not measured.

- Every frame goes through `onFrame(frame)`. The frame format is the one in the plan (cells, real, desks, sun, glare_h,
  lat_ms, moves). A live source only has to call that function.
- `?t=12` in the address starts the clock at 12:00 for rehearsal.
- P1 (2026-10-16): `demo/server.py` (FastAPI, read-only) serves `/api/frame`, `/api/events`, and a flow viewer at `/flow`. Reading 1,000 cells took p50 1.3-1.6 s (7 reads, one PC); see the plan, section 5. Usage: `demo/README.md`. The page `static/index.html` is not yet wired to the live frames.
- Latency to expect: a one-day closed loop on 1,000 cells (10 MNs x 100 cells) finished without errors, but p95 was 4.4 to
  6.7 s when all ten zones ran at once and 1.8 to 2.9 s when run as two batches of five (`sw/edge_ai/results/`). The page
  therefore plays a recording by default and treats live mode as the extra.
