# actuator
Polarizer drive software: ESP32 firmware that turns the inner polarizer disc of one control module with a 28BYJ-48 stepper and reports the angle over oneM2M (the oneM2M part is not written yet).

## Prototype (one control module, ESP32, 28BYJ-48 + ULN2003)
- `src/cell_logic.h`: angle to half steps, half-step coil table, a position-keeping `Stepper` (homing first, then one half step per call), serial command parser, watchdog. No hardware calls, tested on the PC:
  `g++ -std=c++17 -I src tests_host/test_logic.cpp -o test_logic && ./test_logic` (passes, 2026-10-18).
- `src/main.cpp`: ULN2003 IN1..IN4 on GPIO 13, 26, 14, 27 (`N_CELLS = 1`, GPIO 12 is a strapping pin, avoid it). One half step every 2 ms, the serial parser is never blocked.
  Serial 115200: `A <cell> <deg>` (cell 0), `ALL <deg>`, `OPEN`. Replies `OK <cell> <disc deg> <target half steps>`, `HOMING` at boot and `HOMED` when done.
  Angles follow polagrid (0 = open, 90 = closed). The disc turns `STEPS_PER_DISC_DEG` = 4096 x (150 / 24) / 360, about 71.1 half steps per degree (`hw/README.md`).
- Homing: at boot the motor drives `HOME_OVERDRIVE_DEG` = 100 deg of disc back toward the stop pin, then position 0 is set. Coils switch off when the motor is idle.
- Watchdog: no command for `WATCHDOG_MS` (30 min by default) opens the cell.
- Build: `pio run` (PlatformIO, ESP32 Arduino). Built 2026-10-18 (RAM 6.6 %, flash 22.7 %).

Not done: the half steps per turn (4096), the step interval (2 ms) and the turning direction are typical values to calibrate on the real module (flip `phase` direction if the disc turns the wrong way). No oneM2M or MQTT yet. The earlier Wokwi simulation (servo) was removed with the servo hardware; the 28BYJ-48 is not simulated.
