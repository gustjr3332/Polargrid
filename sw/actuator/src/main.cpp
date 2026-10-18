// One-cell polarizer control module (ESP32, Arduino framework, 28BYJ-48 + ULN2003).
// Serial commands (115200): "A 0 45", "ALL 90", "OPEN". Replies "OK <cell> <disc deg> <target half steps>".
#include <Arduino.h>
#include "cell_logic.h"

const int MOTOR_PINS[4] = {13, 26, 14, 27};   // ULN2003 IN1..IN4; GPIO 12 is a strapping pin, avoid it
constexpr uint32_t STEP_US = 2000;            // 500 half steps/s, slow enough for the 28BYJ-48 (calibrate)
Cells cells;
Stepper motor[N_CELLS];
float shown[N_CELLS] = {-1};

void coils(int mask) {
  for (int b = 0; b < 4; b++) digitalWrite(MOTOR_PINS[b], mask >= 0 && (mask >> b & 1));
}

void apply() {
  for (int k = 0; k < N_CELLS; k++) {
    if (cells.disc[k] == shown[k]) continue;
    shown[k] = cells.disc[k];
    motor[k].target = stepsFromDisc(cells.disc[k]);
    Serial.printf("OK %d %.1f %ld\n", k, cells.disc[k], motor[k].target);
  }
}

void setup() {
  Serial.begin(115200);
  for (int b = 0; b < 4; b++) pinMode(MOTOR_PINS[b], OUTPUT);
  cells.lastCmdMs = millis();
  Serial.println("HOMING");
}

void loop() {
  static char buf[32]; static int n = 0;
  static uint32_t lastStepUs = 0;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (n) { buf[n] = 0; if (parseCommand(buf, cells, millis()) != Result::Ok) Serial.println("ERR"); }
      n = 0;
    } else if (n < (int)sizeof(buf) - 1) buf[n++] = ch;
  }
  if (watchdog(cells, millis())) Serial.println("WATCHDOG open");
  apply();
  if (micros() - lastStepUs >= STEP_US) {      // one half step at a time, never blocks the serial parser
    lastStepUs = micros();
    bool wasHomed = motor[0].homed;
    coils(motor[0].step());
    if (!wasHomed && motor[0].homed) Serial.println("HOMED");
  }
}
