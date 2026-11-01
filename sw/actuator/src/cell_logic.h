#pragma once
// Hardware-free logic of one control module (one cell), so it can be tested on the PC.
// Angle convention is the one polagrid uses: disc angle vs the fixed front film, 0 = open, 90 = closed.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

constexpr int N_CELLS = 1;   // one control module per central module in the prototype; raise it to drive more
constexpr float DISC_MAX_DEG = 90.0f;
// 28BYJ-48 half-step drive, timing pulley on the disc rim belt (hw/README.md). The half steps per turn is the typical
// datasheet value (about 4096); calibrate it on the real module with the 10-point test.
constexpr float HALF_STEPS_PER_REV = 4096.0f;
// 10-22: belt drive. 40T MXL pulley (pitch dia 40 x 2.032 / pi) on a O179 disc with a 76MXL3.2 strip glued teeth-out; the belt
// pitch line is about 0.9 mm outside the rim (estimate, calibrate on the real cell).
constexpr float PULLEY_PITCH_R_MM = 40 * 2.032f / (2 * 3.14159265f);
constexpr float DISC_PITCH_R_MM = 89.5f + 0.9f;
constexpr float GEAR_RATIO = DISC_PITCH_R_MM / PULLEY_PITCH_R_MM;
constexpr float STEPS_PER_DISC_DEG = HALF_STEPS_PER_REV * GEAR_RATIO / 360.0f;   // about 79
// At boot drive this far toward the stop, so wherever the disc was it ends on it. 10-31: 0 = no homing, because there is no
// stop yet and 100 deg is longer than the 98 deg belt arc, so every boot pulled the pulley off the belt end. Until a stop exists
// the disc must be set by hand to the open position before power-on (position 0 = where it was at boot).
constexpr float HOME_OVERDRIVE_DEG = 0.0f;

#ifndef WATCHDOG_MS
#define WATCHDOG_MS 1800000UL              // same 30 min as polagrid/zone.py WATCHDOG_MIN
#endif

inline float clampDisc(float d) { return d < 0 ? 0 : (d > DISC_MAX_DEG ? DISC_MAX_DEG : d); }

// 10-31: the pulley was engaged so the disc sweeps about 40..130 deg of film angle, not 0..90. Measured on the real cell with
// the desk BH1750 behind the disc (two sweeps, 5 deg steps, a few readings each): the dark end is near motor 40 deg (the
// minima centre at 45 and 35), the bright end is at the motor 0 stop (17.5 lux against about 1.7 at the dark end; the 90 deg end
// read about the same, so that choice is +-). The film's true open (0 or 180 deg) is outside the motor range, so "open" is
// only partly open. A command angle (0 = open, 90 = closed) is mapped linearly between these two motor angles. Re-measure
// after the cell is re-seated or the film is turned.
constexpr float MOTOR_OPEN_DEG = 0.0f;     // motor angle of the brightest reading
// 11-01: two more sweeps (3 and 5 readings per 10 deg, command angle) put the darkest reading at command 70..75 deg = motor ~31..33,
// and a cos^2 fit puts it at 75 (motor 33); at command 90 the old 40 read 10% of the open lux instead of ~0.
constexpr float MOTOR_CLOSED_DEG = 33.0f;  // motor angle of the darkest reading

inline float motorFromDisc(float disc) {
  return MOTOR_OPEN_DEG + clampDisc(disc) / DISC_MAX_DEG * (MOTOR_CLOSED_DEG - MOTOR_OPEN_DEG);
}
inline float discFromMotor(float motor) { return (motor - MOTOR_OPEN_DEG) / (MOTOR_CLOSED_DEG - MOTOR_OPEN_DEG) * DISC_MAX_DEG; }

inline long stepsFromDisc(float disc) { return (long)(motorFromDisc(disc) * STEPS_PER_DISC_DEG + 0.5f); }

// Half-step coil pattern for IN1..IN4 of the ULN2003 (bit 0 = IN1).
constexpr uint8_t HALF_STEP[8] = {0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001};

// Position keeping of one stepper. pos counts half steps from the stop (0 = open). Moving up = disc angle up.
struct Stepper {
  long pos = 0, target = 0;
  int phase = 0;
  bool homed = false;
  long homeLeft = (long)(HOME_OVERDRIVE_DEG * STEPS_PER_DISC_DEG + 0.5f);
  // One half step toward the target (or toward the stop while homing). Returns the coil mask, or -1 when idle
  // (coils off, the motor does not heat while it waits).
  int step() {
    if (!homed) {
      if (homeLeft-- > 0) { phase = (phase + 7) % 8; return HALF_STEP[phase]; }   // toward the stop
      homed = true; pos = 0;
      return -1;
    }
    if (pos == target) return -1;
    phase = (phase + (target > pos ? 1 : 7)) % 8;
    pos += target > pos ? 1 : -1;
    return HALF_STEP[phase];
  }
};

struct Cells {
  float disc[N_CELLS] = {};
  uint32_t lastCmdMs = 0;
  bool privacy = false;   // privacy mode: the user wants every cell dark, so the fail-safe must not open them
};

enum class Result { Ok, BadCommand, BadCell };

// "A <cell> <deg>", "ALL <deg>", "OPEN", "PRIV <0|1>", "FAILSAFE". Any valid command counts as the controller heartbeat.
// OPEN is the user's own override (button, serial) and also ends privacy mode. FAILSAFE is the cell's own decision
// (link lost, nonsense command) and opens the cells unless privacy mode is on.
inline Result parseCommand(const char* line, Cells& c, uint32_t nowMs) {
  int i; float d;
  if (sscanf(line, "A %d %f", &i, &d) == 2) {
    if (i < 0 || i >= N_CELLS) return Result::BadCell;
    c.disc[i] = clampDisc(d);
  } else if (sscanf(line, "ALL %f", &d) == 1) {
    for (int k = 0; k < N_CELLS; k++) c.disc[k] = clampDisc(d);
  } else if (strncmp(line, "OPEN", 4) == 0) {
    c.privacy = false;
    for (int k = 0; k < N_CELLS; k++) c.disc[k] = 0;
  } else if (sscanf(line, "PRIV %d", &i) == 1) {
    c.privacy = i != 0;
  } else if (strncmp(line, "FAILSAFE", 8) == 0) {
    if (!c.privacy) for (int k = 0; k < N_CELLS; k++) c.disc[k] = 0;
  } else {
    return Result::BadCommand;
  }
  c.lastCmdMs = nowMs;
  return Result::Ok;
}

// Bluetooth line protocol (env:bt). The bridge on the laptop (sw/edge_ai/tools/bt_bridge.py) does the CSE side.
// Bridge -> cell: the commands above, plus "PING" after each CSE reply (the link is alive; not a controller heartbeat).
// Cell -> bridge, besides the usual "OK ..." and log lines:
//   "POS <disc deg>"     motor idle at a new position (any cause); the bridge PUTs state
//   "DESK <lux>"         desk reading once the disc reached the last BT "A"/"FAILSAFE"; the bridge's desk reply
//   "LUX <cell> <desk>"  every 10 s, -1 = that sensor did not answer
inline bool isPing(const char* line) { return strcmp(line, "PING") == 0; }
// Half steps a bridge line asks a desk reply at, or -1. FAILSAFE waits at 0 like a nonsense angle on the Wi-Fi path.
inline long replySteps(const char* line) {
  int i; float d;
  if (sscanf(line, "A %d %f", &i, &d) == 2) return stepsFromDisc(d);
  return strncmp(line, "FAILSAFE", 8) == 0 ? 0 : -1;
}
inline int posLine(char* b, size_t n, float disc) { return snprintf(b, n, "POS %.1f\n", disc); }
inline int deskLine(char* b, size_t n, float desk) { return snprintf(b, n, "DESK %.1f\n", desk); }
inline int luxLine(char* b, size_t n, float cell, float desk) { return snprintf(b, n, "LUX %.1f %.1f\n", cell, desk); }

// Fail-safe: no command for WATCHDOG_MS, so let the light in (not in privacy mode). Returns true when it opened the cells.
inline bool watchdog(Cells& c, uint32_t nowMs) {
  if (c.privacy || nowMs - c.lastCmdMs <= WATCHDOG_MS) return false;
  bool any = false;
  for (int k = 0; k < N_CELLS; k++) { any |= c.disc[k] > 0; c.disc[k] = 0; }
  return any;
}
