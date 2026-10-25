// One-cell polarizer control module (ESP32, Arduino framework, 28BYJ-48 + ULN2003, two BH1750, open-all button).
// Serial commands (115200): "A 0 45", "ALL 90", "OPEN". Replies "OK <cell> <disc deg> <target half steps>".
// oneM2M: a network task on core 0 talks plain HTTP to the MN-CSE (onem2m_logic.h); loop() on core 1 only drives the
// stepper, so HTTP waits never delay a half step. The two sides share a command queue and a few status words.
// -DUSE_BT (env:bt): no Wi-Fi; a Bluetooth SPP task takes the network task's place and a laptop bridge talks to the CSE.
#include <Arduino.h>
#include <Wire.h>
#ifdef USE_BT
#include <BluetoothSerial.h>
#else
#include <HTTPClient.h>
#include <ArduinoOTA.h>
#include <WiFi.h>
#endif
#include "cell_logic.h"
#include "onem2m_logic.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif
#ifndef CELL_ROW   // a secrets.h from before the position was added
#define CELL_ROW 0
#define CELL_COL 0
#endif

const int MOTOR_PINS[4] = {13, 14, 27, 26};   // ULN2003 IN1..IN4; GPIO 12 is a strapping pin (ULN2003 on it broke flashing), avoid it
const int BUTTON_PIN = 25;                    // to GND, internal pull-up: opens the cell
const uint8_t CELL_SENSOR = 0x23, DESK_SENSOR = 0x5C;   // BH1750 ADDR to GND / to 3V3
constexpr uint32_t STEP_US = 2000;            // 500 half steps/s, slow enough for the 28BYJ-48 (calibrate)
constexpr uint32_t POLL_MS = 2000;            // command/la poll interval
constexpr uint32_t REPORT_MS = 10000;         // periodic desk and cell lux CINs
constexpr uint32_t APPLY_WAIT_MS = 25000;     // give up the desk reply if the disc has not arrived (controller waits 30 s)
Cells cells;
Stepper motor[N_CELLS];
float shown[N_CELLS] = {-1};

QueueHandle_t cmdQueue;                       // "A 0 <deg>" lines from the network task, parsed in loop()
volatile long motorAt = -1;                   // half steps from the stop, -1 while homing
volatile bool motorIdle = false;

#ifdef USE_BT
BluetoothSerial SerialBT;
QueueHandle_t btOut;                          // whole lines for the BT task
// USB serial at once, a copy of each line to the BT task: a slow BT link never stalls the stepper loop.
struct Tee : Print {
  char line[48]; int n = 0;
  size_t write(uint8_t c) override {
    if (c == '\n') { line[n] = 0; xQueueSend(btOut, line, 0); n = 0; }
    else if (c != '\r' && n < (int)sizeof(line) - 1) line[n++] = c;
    return Serial.write(c);
  }
} Out;
#else
HardwareSerial& Out = Serial;
#endif

void coils(int mask) {
  for (int b = 0; b < 4; b++) digitalWrite(MOTOR_PINS[b], mask >= 0 && (mask >> b & 1));
}

void apply() {
  for (int k = 0; k < N_CELLS; k++) {
    if (cells.disc[k] == shown[k]) continue;
    shown[k] = cells.disc[k];
    motor[k].target = stepsFromDisc(cells.disc[k]);
    Out.printf("OK %d %.1f %ld\n", k, cells.disc[k], motor[k].target);
  }
}

bool startLux(uint8_t addr) {   // BH1750 continuous high resolution mode, a new value every 120 ms
  Wire.beginTransmission(addr);
  Wire.write(0x10);
  return Wire.endTransmission() == 0;
}

float readLux(uint8_t addr) {   // raw / 1.2 lux; -1 when the sensor does not answer (it is set up again for next time)
  if (Wire.requestFrom(addr, (uint8_t)2) != 2) { startLux(addr); return -1; }
  uint16_t raw = Wire.read() << 8;
  raw |= Wire.read();
  return raw / 1.2f;
}

#ifdef USE_BT
// ---- Bluetooth task (core 0): line protocol in cell_logic.h; the laptop bridge does what netTask does against the CSE ----

void btTask(void*) {
  Wire.begin(21, 22);                         // I2C only from this task
  startLux(CELL_SENSOR);
  startLux(DESK_SENSOR);
  SerialBT.begin("polagrid-cell");
  char buf[32], line[48];
  int n = 0;
  long pendingSteps = -1, sentAt = -2;        // sentAt: position last sent as POS
  uint32_t pendingSince = 0, lastReport = 0, lastReply = millis();
  bool linkReported = false, had = false;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(50));
    bool has = SerialBT.hasClient();
    if (has && !had) sentAt = -2;             // a new connection gets the position again
    had = has;
    while (xQueueReceive(btOut, line, 0) == pdTRUE) SerialBT.printf("%s\n", line);
    while (SerialBT.available()) {
      char ch = SerialBT.read();
      if (ch == '\n' || ch == '\r') {
        if (!n) continue;
        buf[n] = 0; n = 0;
        if (isPing(buf)) { lastReply = millis(); continue; }
        long s = replySteps(buf);
        if (s >= 0) { pendingSteps = s; pendingSince = millis(); }
        xQueueSend(cmdQueue, buf, 0);
      } else if (n < (int)sizeof(buf) - 1) buf[n++] = ch;
    }
    // no PING (BT gone, bridge stopped or CSE silent) for a minute: open (not in privacy mode), as on Wi-Fi
    if (m2m::linkLost(lastReply, millis(), linkReported)) {
      xQueueSend(cmdQueue, "FAILSAFE", 0);
      Serial.println("LINK LOST");
    }
    long at = motorAt;
    if (at >= 0 && motorIdle) {
      if (at != sentAt) { posLine(line, sizeof line, m2m::discFromSteps(at)); SerialBT.print(line); sentAt = at; }
      if (pendingSteps >= 0 && at == pendingSteps) {
        vTaskDelay(pdMS_TO_TICKS(250));       // let the sensor finish a reading at the new angle
        float desk = readLux(DESK_SENSOR);
        if (desk >= 0) { deskLine(line, sizeof line, desk); SerialBT.print(line); }
        else { Serial.println("ERR desk sensor"); SerialBT.print("ERR desk sensor\n"); }
        pendingSteps = -1;
      }
    }
    if (pendingSteps >= 0 && millis() - pendingSince > APPLY_WAIT_MS) pendingSteps = -1;   // overridden (button, watchdog)
    if (millis() - lastReport >= REPORT_MS) {
      lastReport = millis();
      float desk = readLux(DESK_SENSOR), cell = readLux(CELL_SENSOR);
      luxLine(line, sizeof line, cell, desk);
      SerialBT.print(line);
    }
  }
}

#else
// ---- network task (core 0). shortcut: HTTP polling only; swap poll() and send() for MQTT later, the plan stays. ----

const std::string RUN = RUN_ID;

int send(const m2m::Req& r, std::string* reply = nullptr) {
  static uint32_t seq = 0;
  HTTPClient http;
  http.setConnectTimeout(2000);
  http.setTimeout(3000);
  if (!http.begin(m2m::url(CSE_HOST, CSE_NAME, r.path).c_str())) return -1;
  http.addHeader("X-M2M-Origin", r.origin.c_str());
  http.addHeader("X-M2M-RI", ("esp" + std::to_string(++seq)).c_str());
  http.addHeader("X-M2M-RVI", "3");
  http.addHeader("Accept", "application/json");
  http.addHeader("Content-Type", m2m::contentType(r.ty).c_str());
  int code = r.method == "GET" ? http.GET()
           : r.method == "PUT" ? http.PUT((uint8_t*)r.body.data(), r.body.size())
                               : http.POST((uint8_t*)r.body.data(), r.body.size());
  if (reply && code > 0) *reply = http.getString().c_str();
  http.end();
  if (code < 200 || code >= 300) Serial.printf("NET %d %s /%s\n", code, r.method.c_str(), r.path.c_str());
  return code;
}

// ACP ri from a create reply, or by retrieving the ACP that is already there (409).
bool acpRi(const std::string& rn, const std::string& owner, std::string& ri) {
  std::string reply;
  int code = send(m2m::acpReq(RUN, rn, owner), &reply);
  if (code == 409) code = send(m2m::acpGetReq(rn), &reply);
  return code >= 200 && code < 300 && m2m::jsonString(reply, "ri", ri);
}

bool provision() {
  std::string envAcp, cellAcp;
  if (!acpRi(RUN + "envacp", m2m::envOrig(RUN), envAcp) ||
      !acpRi(m2m::cellRn(RUN, CELL_INDEX) + "acp", m2m::cellOrig(RUN, CELL_INDEX), cellAcp)) return false;
  for (auto& r : m2m::resourceReqs(RUN, CELL_INDEX, envAcp, cellAcp, CELL_ROW, CELL_COL)) {
    int code = send(r);
    if (code != 409 && (code < 200 || code >= 300)) return false;
  }
  return true;
}

void netTask(void*) {
  Wire.begin(21, 22);                         // I2C only from this task
  startLux(CELL_SENSOR);
  startLux(DESK_SENSOR);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  bool ready = false;
  int fails = 0, notFound = 0, published = -1;
  m2m::CommandGate gate;
  std::string pendingCmd;
  long pendingSteps = 0;
  uint32_t pendingSince = 0, lastPoll = 0, lastReport = 0, lastState = 0, offlineSince = millis(), lastReply = millis();
  bool linkReported = false;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(50));
    if (m2m::linkLost(lastReply, millis(), linkReported)) {   // no CSE reply for a minute: open (not in privacy mode)
      xQueueSend(cmdQueue, "FAILSAFE", 0);
      Serial.println("LINK LOST");
    }
    if (WiFi.status() != WL_CONNECTED) {
      ready = false;
      if (millis() - offlineSince > 15000) { WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASS); offlineSince = millis(); }
      continue;
    }
    offlineSince = millis();
    if (!ready) {
      ready = provision();
      fails = ready ? 0 : fails + 1;
      Serial.println(ready ? "CSE ready" : "CSE setup failed");
      if (!ready) vTaskDelay(pdMS_TO_TICKS(m2m::backoffMs(fails)));
      published = -1;                         // state on the CSE may be the 100 of a fresh FlexContainer
      continue;
    }
    if (millis() - lastPoll >= POLL_MS) {
      lastPoll = millis();
      std::string reply, cmd;
      float angle;
      int code = send(m2m::pollReq(RUN, CELL_INDEX), &reply);
      if (code < 0) {
        vTaskDelay(pdMS_TO_TICKS(m2m::backoffMs(++fails)));
        continue;
      }
      fails = 0;
      lastReply = millis();
      // 404 is normal before the first command; if it lasts a minute the MN may have been reset, so provision again
      notFound = code == 404 ? notFound + 1 : 0;
      if (code == 403 || notFound >= 30) { ready = false; notFound = 0; }
      if (code == 404) gate.noneYet();
      bool stale = code == 200 && !gate.baselined;   // the first command seen after boot is an old one
      if (code == 200 && m2m::parseCommandCin(reply, CELL_INDEX, cmd, angle) && gate.accept(cmd)) {
        bool priv = m2m::commandPrivacy(reply);   // privacy: every disc closed, whatever the angle list says
        bool sane = priv || m2m::angleSane(angle);
        char line[32];
        if (sane) {
          xQueueSend(cmdQueue, priv ? "PRIV 1" : "PRIV 0", 0);
          snprintf(line, sizeof line, "A 0 %.1f", priv ? DISC_MAX_DEG : angle);
          xQueueSend(cmdQueue, line, 0);
        } else {
          xQueueSend(cmdQueue, "FAILSAFE", 0);   // nonsense angle: the controller is confused, let the light in
          Serial.println("BAD ANGLE");
        }
        pendingCmd = cmd;
        pendingSteps = sane ? stepsFromDisc(priv ? DISC_MAX_DEG : angle) : 0;
        pendingSince = millis();
      } else if (stale && gate.baselined) Serial.println("SKIP old command after boot");
    }
    long at = motorAt;
    if (at >= 0 && motorIdle) {
      int level = m2m::openLevel(m2m::discFromSteps(at));
      if (level != published && millis() - lastState >= 1000) {   // state on change, retried at most once a second
        lastState = millis();
        if (send(m2m::stateReq(RUN, CELL_INDEX, level)) == 200) published = level;
      }
      if (!pendingCmd.empty() && at == pendingSteps) {
        vTaskDelay(pdMS_TO_TICKS(250));         // let the sensor finish a reading at the new angle
        float desk = readLux(DESK_SENSOR);
        if (desk >= 0) send(m2m::desksReq(RUN, pendingCmd, {desk}));
        else Serial.println("ERR desk sensor");   // no reading: the controller times out and keeps its old table
        pendingCmd.clear();
      }
    }
    if (!pendingCmd.empty() && millis() - pendingSince > APPLY_WAIT_MS) pendingCmd.clear();   // overridden (button, watchdog)
    if (millis() - lastReport >= REPORT_MS) {
      lastReport = millis();
      float desk = readLux(DESK_SENSOR), cell = readLux(CELL_SENSOR);
      if (desk >= 0) send(m2m::desksReq(RUN, "t" + std::to_string(millis() / 1000), {desk}));
      if (cell >= 0) send(m2m::cellLuxReq(RUN, CELL_INDEX, cell));
    }
  }
}
#endif

// ---- stepper loop (core 1) ----

void setup() {
  Serial.begin(115200);
  for (int b = 0; b < 4; b++) pinMode(MOTOR_PINS[b], OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  cmdQueue = xQueueCreate(4, 32);
  cells.lastCmdMs = millis();
#ifdef USE_BT
  btOut = xQueueCreate(8, 48);
  Out.println("HOMING");
  xTaskCreatePinnedToCore(btTask, "bt", 8192, nullptr, 1, nullptr, 0);
#else
  Out.println("HOMING");
  xTaskCreatePinnedToCore(netTask, "net", 12288, nullptr, 1, nullptr, 0);
#endif
}

void loop() {
  static char buf[32]; static int n = 0;
  static uint32_t lastStepUs = 0, pressedMs = 0;
  static bool wasDown = false;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (n) { buf[n] = 0; if (parseCommand(buf, cells, millis()) != Result::Ok) Out.println("ERR"); }
      n = 0;
    } else if (n < (int)sizeof(buf) - 1) buf[n++] = ch;
  }
  char line[32];
  while (xQueueReceive(cmdQueue, line, 0) == pdTRUE)
    if (parseCommand(line, cells, millis()) != Result::Ok) Out.println("ERR net");
  bool down = digitalRead(BUTTON_PIN) == LOW;   // a press counts after 50 ms held (debounce)
  if (down && !wasDown) pressedMs = millis();
  if (down && pressedMs && millis() - pressedMs >= 50) { parseCommand("OPEN", cells, millis()); pressedMs = 0; Out.println("BUTTON open"); }
  wasDown = down;
  if (watchdog(cells, millis())) Out.println("WATCHDOG open");
  static bool wasPrivacy = false;
  if (cells.privacy != wasPrivacy) Out.println((wasPrivacy = cells.privacy) ? "PRIVACY on" : "PRIVACY off");
#ifndef USE_BT
  static bool otaOn = false;                   // wireless upload (env:ota); begin once Wi-Fi is up, handle() is cheap
  if (!otaOn && WiFi.status() == WL_CONNECTED) {
    ArduinoOTA.setHostname("polagrid-cell");
#ifdef OTA_PASS
    ArduinoOTA.setPassword(OTA_PASS);
#endif
    ArduinoOTA.onStart([]() { coils(-1); Serial.println("OTA start"); });   // coils off: the stepper stops while flashing
    ArduinoOTA.begin();
    otaOn = true;
  }
  if (otaOn) ArduinoOTA.handle();
#endif
  apply();
  if (micros() - lastStepUs >= STEP_US) {      // one half step at a time, never blocks the serial parser
    lastStepUs = micros();
    bool wasHomed = motor[0].homed;
    coils(motor[0].step());
    if (!wasHomed && motor[0].homed) Out.println("HOMED");
    motorAt = motor[0].homed ? motor[0].pos : -1;
    motorIdle = motor[0].homed && motor[0].pos == motor[0].target;
  }
}
