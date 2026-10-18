// g++ -std=c++17 -I src tests_host/test_logic.cpp -o test_logic && ./test_logic
#include <cassert>
#include <cstdio>
#include "cell_logic.h"

int main() {
  assert(servoFromDisc(0) == 180 && servoFromDisc(90) == 0 && servoFromDisc(45) == 90);
  assert(servoFromDisc(-10) == 180 && servoFromDisc(120) == 0);          // clamped to the 0..90 range

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
  puts("all tests passed");
}
