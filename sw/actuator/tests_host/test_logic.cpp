// g++ -std=c++17 -I src tests_host/test_logic.cpp -o test_logic && ./test_logic
#include <cassert>
#include <cstdio>
#include "cell_logic.h"

int main() {
  assert(stepsFromDisc(0) == 0 && stepsFromDisc(90) == 6400 && stepsFromDisc(45) == 3200);
  assert(stepsFromDisc(-10) == 0 && stepsFromDisc(120) == 6400);         // clamped to the 0..90 range

  Cells c;
  assert(parseCommand("A 0 45", c, 100) == Result::Ok && c.disc[0] == 45 && c.lastCmdMs == 100);
  assert(parseCommand("A 1 10", c, 200) == Result::BadCell && c.lastCmdMs == 100);
  assert(parseCommand("hello", c, 200) == Result::BadCommand && c.lastCmdMs == 100);
  assert(parseCommand("ALL 200", c, 300) == Result::Ok && c.disc[0] == 90);

  assert(!watchdog(c, 300 + WATCHDOG_MS));                                // exactly at the limit: still closed
  assert(watchdog(c, 301 + WATCHDOG_MS) && c.disc[0] == 0);
  assert(!watchdog(c, 302 + WATCHDOG_MS));                                // already open: no repeat
  parseCommand("OPEN", c, 400);
  assert(c.disc[0] == 0);

  // stepper: homes first (pos = 0 at the stop), then reaches the target one half step at a time
  Stepper m;
  m.target = 100;
  long homing = 0;
  while (!m.homed) { assert(m.step() >= 0 || m.homed); homing++; }
  assert(homing == (long)(HOME_OVERDRIVE_DEG * STEPS_PER_DISC_DEG + 0.5f) + 1 && m.pos == 0);
  int mask = 0; long n = 0;
  while ((mask = m.step()) >= 0) { assert(mask == HALF_STEP[m.phase]); n++; }
  assert(n == 100 && m.pos == 100 && m.step() == -1);                    // idle again: coils off
  m.target = 40;
  n = 0; while (m.step() >= 0) n++;
  assert(n == 60 && m.pos == 40);                                         // reverses
  // up and back down returns to the same coil phase pattern (no drift in the table)
  Stepper z; z.homed = true; z.target = 8; while (z.step() >= 0) {}
  assert(z.phase == 0); z.target = 0; while (z.step() >= 0) {}
  assert(z.phase == 0 && z.pos == 0);
  puts("all tests passed");
}
