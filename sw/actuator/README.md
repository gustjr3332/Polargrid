# actuator
Polarizer drive software: ESP32 firmware that turns the inner polarizer of each cell (servo) and reports the angle over oneM2M.

> 10-18: the hardware changed to a 150 mm cell driven by a 28BYJ-48 stepper (`hw/README.md`). The firmware below still drives a servo and has to be rewritten for the stepper (4-pin half-step drive, homing against a stop, angle to steps). The angle convention, parser and watchdog stay.

## Prototype (one control module, ESP32, Wokwi)
- `src/cell_logic.h`: angle to servo mapping, serial command parser, watchdog. No hardware calls, tested on the PC:
  `g++ -std=c++17 -I src tests_host/test_logic.cpp -o test_logic && ./test_logic` (passes, 2026-10-16).
- `src/main.cpp`: one servo on GPIO 13 (`N_CELLS = 1`, one control module per central module; more modules would use 26, 14, 27, never the strapping pin 12). Serial 115200: `A <cell> <deg>` (cell 0), `ALL <deg>`, `OPEN`.
  Angles follow polagrid (0 = open, 90 = closed). Servo = 180 - 2 x disc angle (2:1 gear, `hw/README.md`).
- Watchdog: no command for `WATCHDOG_MS` opens all cells (30 min by default, 10 s in `platformio.ini` for the simulator).
- Simulator: `diagram.json` + `wokwi.toml` (Wokwi for VS Code or wokwi.com). Build first with PlatformIO
  (`pio run`), then start the simulation.

Tested 2026-10-16: `pio run` builds (RAM 6.7 %, flash 23.3 %). In Wokwi (serial over `rfc2217://localhost:4000`, set by
`rfc2217ServerPort` in `wokwi.toml`) `A`, `ALL` and `OPEN` moved the servos as expected, bad input returned `ERR`, and
the watchdog opened the cells after 10 s without a command. Simulation only, nothing was measured on hardware.
That run used the earlier 4-servo build; the one-servo build (10-18) passed the PC test only, `pio run` and Wokwi were not rerun.

Not done: `SERVO_OPEN_DEG` is a placeholder until the real panel is calibrated. No oneM2M or MQTT yet.
