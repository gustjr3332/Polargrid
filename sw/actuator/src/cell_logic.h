#pragma once
// Hardware-free logic of one control module (one cell), so it can be tested on the PC.
// Angle convention is the one polagrid uses: disc angle vs the fixed front film, 0 = open, 90 = closed.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

constexpr int N_CELLS = 1;   // one control module per central module in the prototype; raise it to drive more
constexpr float DISC_MAX_DEG = 90.0f;
// 28BYJ-48 half-step drive, Z24 pinion on the Z150 disc rim (hw/README.md). The half steps per turn is the typical
// datasheet value (about 4096); calibrate it on the real module with the 10-point test.
constexpr float HALF_STEPS_PER_REV = 4096.0f;
constexpr float GEAR_RATIO = 150.0f / 24.0f;
constexpr float STEPS_PER_DISC_DEG = HALF_STEPS_PER_REV * GEAR_RATIO / 360.0f;   // about 71.1
constexpr float HOME_OVERDRIVE_DEG = 100.0f;   // at boot drive this far toward the stop, so wherever the disc was it ends on it

#ifndef WATCHDOG_MS
#define WATCHDOG_MS 1800000UL              // same 30 min as polagrid/zone.py WATCHDOG_MIN
#endif

inline float clampDisc(float d) { return d < 0 ? 0 : (d > DISC_MAX_DEG ? DISC_MAX_DEG : d); }

inline long stepsFromDisc(float disc) { return (long)(clampDisc(disc) * STEPS_PER_DISC_DEG + 0.5f); }

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

// Fail-safe: no command for WATCHDOG_MS, so let the light in (not in privacy mode). Returns true when it opened the cells.
inline bool watchdog(Cells& c, uint32_t nowMs) {
  if (c.privacy || nowMs - c.lastCmdMs <= WATCHDOG_MS) return false;
  bool any = false;
  for (int k = 0; k < N_CELLS; k++) { any |= c.disc[k] > 0; c.disc[k] = 0; }
  return any;
}
