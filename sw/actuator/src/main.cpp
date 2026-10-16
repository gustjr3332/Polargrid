// 4-cell polarizer panel prototype (ESP32, Arduino framework). Runs in Wokwi: see diagram.json.
// Serial commands (115200): "A 2 45", "ALL 90", "OPEN". Replies "OK <cell> <disc deg> <servo deg>".
#include <Arduino.h>
#include <ESP32Servo.h>
#include "cell_logic.h"

const int SERVO_PINS[N_CELLS] = {13, 12, 14, 27};
Servo servos[N_CELLS];
Cells cells;
float shown[N_CELLS] = {-1, -1, -1, -1};

void apply() {
  for (int k = 0; k < N_CELLS; k++) {
    if (cells.disc[k] == shown[k]) continue;
    shown[k] = cells.disc[k];
    servos[k].write(servoFromDisc(cells.disc[k]));
    Serial.printf("OK %d %.1f %d\n", k, cells.disc[k], servoFromDisc(cells.disc[k]));
  }
}

void setup() {
  Serial.begin(115200);
  for (int k = 0; k < N_CELLS; k++) servos[k].attach(SERVO_PINS[k], 500, 2400);
  cells.lastCmdMs = millis();
  apply();
}

void loop() {
  static char buf[32]; static int n = 0;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (n) { buf[n] = 0; if (parseCommand(buf, cells, millis()) != Result::Ok) Serial.println("ERR"); }
      n = 0;
    } else if (n < (int)sizeof(buf) - 1) buf[n++] = ch;
  }
  if (watchdog(cells, millis())) Serial.println("WATCHDOG open");
  apply();
}
