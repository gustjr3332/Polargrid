#pragma once
// Hardware-free logic of one control module (one cell), so it can be tested on the PC.
// Angle convention is the one polagrid uses: disc angle vs the fixed front film, 0 = open, 90 = closed.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

constexpr int N_CELLS = 1;   // one control module per central module in the prototype; raise it to drive more
constexpr float DISC_MAX_DEG = 90.0f;
constexpr float SERVO_OPEN_DEG = 180.0f;   // servo angle when the disc is open (calibrate on the real panel)
constexpr float SERVO_PER_DISC = -2.0f;    // 2:1 gear, the disc turns the opposite way (hw/README.md)

#ifndef WATCHDOG_MS
#define WATCHDOG_MS 1800000UL              // same 30 min as polagrid/zone.py WATCHDOG_MIN
#endif

inline float clampDisc(float d) { return d < 0 ? 0 : (d > DISC_MAX_DEG ? DISC_MAX_DEG : d); }

inline int servoFromDisc(float disc) {
  float s = SERVO_OPEN_DEG + SERVO_PER_DISC * clampDisc(disc);
  return (int)(s + 0.5f);
}

struct Cells {
  float disc[N_CELLS] = {};
  uint32_t lastCmdMs = 0;
};

enum class Result { Ok, BadCommand, BadCell };

// "A <cell> <deg>", "ALL <deg>", "OPEN". Any valid command counts as the controller heartbeat.
inline Result parseCommand(const char* line, Cells& c, uint32_t nowMs) {
  int i; float d;
  if (sscanf(line, "A %d %f", &i, &d) == 2) {
    if (i < 0 || i >= N_CELLS) return Result::BadCell;
    c.disc[i] = clampDisc(d);
  } else if (sscanf(line, "ALL %f", &d) == 1) {
    for (int k = 0; k < N_CELLS; k++) c.disc[k] = clampDisc(d);
  } else if (strncmp(line, "OPEN", 4) == 0) {
    for (int k = 0; k < N_CELLS; k++) c.disc[k] = 0;
  } else {
    return Result::BadCommand;
  }
  c.lastCmdMs = nowMs;
  return Result::Ok;
}

// Fail-safe: no command for WATCHDOG_MS, so let the light in. Returns true when it opened the cells.
inline bool watchdog(Cells& c, uint32_t nowMs) {
  if (nowMs - c.lastCmdMs <= WATCHDOG_MS) return false;
  bool any = false;
  for (int k = 0; k < N_CELLS; k++) { any |= c.disc[k] > 0; c.disc[k] = 0; }
  return any;
}
