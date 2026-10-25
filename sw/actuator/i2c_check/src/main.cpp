// Wiring check for the two BH1750 on GPIO 21 (SDA) / 22 (SCL): lists every I2C address and prints lux for 0x23 and 0x5C.
#include <Arduino.h>
#include <Wire.h>

static float readLux(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(0x10);                          // continuous high resolution mode
  if (Wire.endTransmission() != 0) return -1;
  delay(180);
  if (Wire.requestFrom(addr, (uint8_t)2) != 2) return -1;
  uint16_t raw = Wire.read() << 8;
  raw |= Wire.read();
  return raw / 1.2f;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
}

void loop() {
  Serial.print("found:");
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Serial.printf(" 0x%02X", a);
  }
  Serial.printf("\ncell 0x23: %.1f lux, desk 0x5C: %.1f lux (-1 = no answer)\n", readLux(0x23), readLux(0x5C));
  delay(1000);
}
