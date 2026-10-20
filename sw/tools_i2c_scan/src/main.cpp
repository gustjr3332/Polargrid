// I2C scanner for the PolaGrid cell: expects BH1750 at 0x23 (cell) and 0x5C (desk) on GPIO 21 (SDA) / 22 (SCL).
#include <Arduino.h>
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
}

void loop() {
  int found = 0;
  bool cell = false, desk = false;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("found 0x%02X\n", a);
      found++;
      cell |= a == 0x23;
      desk |= a == 0x5C;
    }
  }
  Serial.printf("%d device(s): cell 0x23 %s, desk 0x5C %s\n\n", found, cell ? "OK" : "MISSING", desk ? "OK" : "MISSING");
  delay(3000);
}
