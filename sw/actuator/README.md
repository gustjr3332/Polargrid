# actuator
Polarizer drive software: ESP32 firmware that turns the inner polarizer disc of one control module with a 28BYJ-48 stepper and talks to a oneM2M MN-CSE (tinyIoT) over Wi-Fi with plain HTTP, or over Bluetooth through a bridge on the laptop (`env:bt`, below).

## Prototype (one control module, ESP32, 28BYJ-48 + ULN2003)
- `src/cell_logic.h`: angle to half steps, half-step coil table, a position-keeping `Stepper` (homing first, then one half step per call), serial command parser, watchdog. No hardware calls, tested on the PC:
  `g++ -std=c++17 -I src tests_host/test_logic.cpp -o test_logic && ./test_logic` (passes, 2026-10-18).
- `src/onem2m_logic.h`: the oneM2M side without hardware calls: request paths, originators and JSON bodies, the
  command CIN parser, angle to `opeLl`, retry backoff.
  `g++ -std=c++17 -I src tests_host/test_onem2m.cpp -o test_onem2m && ./test_onem2m` (passes, 2026-10-18).
- `src/main.cpp`: ULN2003 IN1..IN4 on GPIO 13, 14, 27, 26 (`N_CELLS = 1`, GPIO 12 is a strapping pin, avoid it: the ULN2003 on it broke flashing on 10-24). One half step every 2 ms, the serial parser is never blocked.
  Serial 115200: `A <cell> <deg>` (cell 0), `ALL <deg>`, `OPEN`. Replies `OK <cell> <disc deg> <target half steps>`, `HOMING` at boot and `HOMED` when done.
  Angles follow polagrid (0 = open, 90 = closed). The disc turns `STEPS_PER_DISC_DEG` = 4096 x (90.4 mm belt pitch radius / 12.94 mm pulley pitch radius, 40T MXL, 10-22) / 360, about 79 half steps per degree (estimate, calibrate) (`hw/README.md`).
  10-31: the pulley is engaged about 40 deg off, so a command angle (0 open .. 90 closed) is mapped linearly onto motor 0..40 deg (`MOTOR_OPEN_DEG` = brightest, `MOTOR_CLOSED_DEG` = darkest in the desk-sensor sweep, `cell_logic.h`). `POS` and the state level use the inverse. The film's true open is outside the motor range, so "open" is only partly open (measured max about 17.5 lux against about 1.7 at the dark end, small sample). Re-measure after re-seating the cell.
- Homing: at boot the motor drives `HOME_OVERDRIVE_DEG` = 100 deg of disc back toward the stop pin, then position 0 is set. Coils switch off when the motor is idle.
- Watchdog: no command for `WATCHDOG_MS` (30 min by default) opens the cell.
- Button on GPIO 25 (to GND, internal pull-up, 50 ms debounce) opens the cell, the same as `OPEN`.
- Build: `pio run` (PlatformIO, ESP32 Arduino). Built 2026-10-18 with the oneM2M part (RAM 14.4 %, flash 74.4 %).
- Fail-safe and privacy (2026-10-20, host tests and `pio run` pass, not run on hardware):
  - The cell opens by itself (serial `FAILSAFE`) when the CSE has not answered for `LINK_LOST_MS` = 60 s, or a fresh command carries an angle that is not a number or outside 0..90. The 30 min watchdog still covers a controller that went silent while the link is fine.
  - Privacy mode: a command CIN with `"mode": "privacy"` (the controller sends angles 90) makes the cell send `PRIV 1` and close fully; the watchdog, the link-loss open and a nonsense angle then leave it dark. A command without `mode` sends `PRIV 0`. The button or serial `OPEN` always opens and ends privacy (the user's own hand). Serial `PRIV <0|1>` sets the flag by hand.
  - After a reboot the disc homes open and the old command is skipped (below), so privacy is restored by the controller's next heartbeat (10 min at most), not by the cell. Mode is not stored in flash.
  - PC side: `evaluate.fail_open(controller)` opens every cell when the AI raises, answers NaN or angles outside 0..90, or the desk reading is broken; `real_cell.py app` takes `POST /mode {"mode": "privacy" | "auto"}` (and answers `/level` with 409 while privacy is on).
- Position in the window: `CELL_ROW`/`CELL_COL` in `secrets.h` say where the cell sits in the window (row 0 = top, col 0 = left, seen from inside); the cell adds them to its `state` as the label `polagrid/<run>/pos/<row>/<col>` so the app draws it there (host test passes, 2026-10-19, not run on hardware).

## oneM2M (HTTP, polling)
The firmware makes the same resources `sw/edge_ai/polagrid/zone.py` makes for one virtual cell, so the polagrid
`Controller` can drive the real cell as cell `p0` of a one-cell zone without changes.

- Settings: copy `src/secrets.example.h` to `src/secrets.h` (git-ignored) and set the Wi-Fi network, `CSE_HOST`
  (the MN as the ESP32 sees it), `CSE_NAME`, `RUN_ID` and `CELL_INDEX`. Without `secrets.h` the build uses the
  placeholders and never connects.
- Setup at every boot, repeated after a lost connection: ACPs `{run}envacp` and `{run}p0acp` as `CAdmin` (if one
  exists, its `ri` is read back), AE `{run}env` with CNTs `sun` and `desks`, AE `{run}p0` with CNT `command`
  (label `polagrid/{run}/command`), FlexContainer `state` (`cod:opeLl`, label `polagrid/{run}/state`) and CNT `lux`.
  A 409 counts as done, so the setup is safe to repeat.
- Commands: every 2 s the cell GETs `{run}p0/command/la` as `C{run}p0`. A new `cmd` id is applied through the
  serial parser (`A 0 <angles[CELL_INDEX]>`), so it also resets the watchdog. The controller's 10 min heartbeat
  carries a new id and counts the same way.
- Replies: when the disc has reached the commanded position, the cell PUTs `state` (`opeLl` = round(100 cos^2(disc)),
  as in zone.py) and POSTs `{"cmd": <id>, "lux": [<desk lux>]}` to `{run}env/desks` as `C{run}env`. That desk reading
  is what the controller waits for (30 s). A full 90 deg turn takes about 12.8 s at 2 ms per half step. `state` is also PUT after any other move (button, watchdog, serial).
- Every 10 s: a desk reading with `cmd` = `t<uptime s>` (zone.py uses `t<unix time>`) and the cell sensor as
  `{"lux": x}` in `{run}p0/lux`.
- Timing: HTTP runs in a FreeRTOS task on core 0. `loop()` on core 1 only reads serial, the button and a command queue
  and steps the motor, so a slow or failed request never delays a half step. Failed connections back off 1, 2, 4 ... 60 s.
  Wi-Fi is restarted after 15 s offline.
- BH1750: cell sensor 0x23 (ADDR to GND), desk sensor 0x5C (ADDR to 3V3), I2C on GPIO 21/22, continuous high
  resolution mode, lux = raw / 1.2. Without a desk reading the cell sends no reply, and the controller times out and
  keeps its old table.

Differences from the virtual cell in zone.py:
- No SUB on `command` and no `poa`; the AEs use `"rr": false`. The cell polls, so the ESP32 needs no inbound server
  (and does not depend on tinyIoT bug 3, GRP fan-out without notifications). Polling sits in `netTask()`/`send()`,
  which MQTT can replace later.
- One extra CNT `{run}p0/lux`. The controller does not read it.
- `state` is written when the integer `opeLl` changes; zone.py writes when the angle changes by more than 0.05 deg.
- The desk list has one value (one desk sensor). The default polagrid `Room` has two desks.
- After a reboot the newest command left in `command` is NOT applied (`m2m::CommandGate`, 2026-10-19): the first command id the cell sees after boot is only remembered, the serial log says `SKIP old command after boot`, and the cell stays open (its safe state) until the controller's heartbeat brings a fresh id (at most 10 min). A 404 (no command yet) lets the first command through. Host test passes; not run on hardware.

## Bluetooth link (env:bt)
For demo rooms where the Wi-Fi, firewall and IP change every time. Built with `-DUSE_BT`, the firmware starts no Wi-Fi
and no OTA. A Bluetooth SPP task (device name `polagrid-cell`) replaces the network task, and the laptop runs
`sw/edge_ai/tools/bt_bridge.py`, which does the CSE side over HTTP. `real_cell.py` and the CSE resources stay the same.
The ESP32 can run from its own adapter; it needs no USB link to the laptop.

- Build and upload over USB once: `pio run -e bt -t upload`. `env:esp32dev` and `env:ota` are the Wi-Fi build as before.
  Built 2026-10-25 with the default partition table (bt: RAM 12.3 %, flash 85.2 %; esp32dev: RAM 15.7 %, flash 77.8 %).
- Bridge to cell: the serial commands (`A 0 <deg>`, `PRIV <0|1>`, `FAILSAFE`, `OPEN`), plus `PING` after every CSE reply.
  `PING` keeps the link alive but is not a controller heartbeat, so the 30 min watchdog still counts only commands.
- Cell to bridge: `OK ...`, `HOMING`, `HOMED` and the other log lines as on USB, and
  - `POS <disc deg>` when the motor stops at a new position (any cause, and again on every new BT connection). The bridge PUTs `state`.
  - `DESK <lux>` once the disc reaches the target of the last `A` (or 0 after `FAILSAFE`), 250 ms after arrival. The bridge posts it to `{run}env/desks` with the command id, which is the reply the controller waits for. No reading gives `ERR desk sensor` and no reply.
  - `LUX <cell> <desk>` every 10 s, `-1` for a sensor that did not answer.
- Fail-open: no `PING` for `LINK_LOST_MS` = 60 s sends `FAILSAFE` (opens unless privacy mode is on). That covers a lost
  BT link, a stopped bridge and a silent CSE. The bridge does the old-command skip after its own start and the angle check.
- The helpers (`isPing`, `replySteps`, `posLine`, `deskLine`, `luxLine`) are in `src/cell_logic.h`, tested in `tests_host/test_logic.cpp`.
- Not run on hardware yet: BT pairing, the SPP link from Windows and its range in the demo room.

Request check without a CSE: `tests_host/zone_capture.py` records what zone.py sends for one cell (fake
`requests.Session`, output in `tests_host/zone_requests.txt`) and `./test_onem2m --print` prints the firmware's
requests in the same line format. Compared 2026-10-18: ACPs, CNTs `sun`/`desks`/`command`, the `state`
FlexContainer and the `state` PUT are byte for byte the same. The AE bodies, the desk count and the extra `lux` CNT
differ as listed above. The command parser is tested on CINs shaped like the one the controller creates through
`grp/fopt`; a real tinyIoT `command/la` reply has not been fed to it yet.

Still needed on the PC side (not in this folder): a driver that runs `Controller(client, RUN_ID, port).setup(1)`
against the same MN, publishes `{run}env/sun` (zone.py makes it from the sun model), and uses a one-desk room.

Not done: the half steps per turn (4096), the step interval (2 ms) and the turning direction are typical values to calibrate on the real module (flip `phase` direction if the disc turns the wrong way). Nothing has run on a real ESP32 yet: Wi-Fi, HTTP against tinyIoT, the BH1750 reads and the button are built
but untested. No MQTT yet. The earlier Wokwi simulation (servo) was removed with the servo hardware; the 28BYJ-48 is not simulated.
