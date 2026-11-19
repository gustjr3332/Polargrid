#pragma once
// Hardware-free oneM2M part of the cell firmware, tested on the PC (tests_host/).
// It rebuilds what sw/edge_ai/polagrid/zone.py makes for one virtual cell, so the polagrid Controller drives a real
// cell unchanged: ACPs {run}p{i}acp and {run}envacp (made as CAdmin), AE {run}env with CNTs sun and desks, AE {run}p{i}
// with CNT command (label polagrid/{run}/command) and FlexContainer state (cod:opeLl, label polagrid/{run}/state).
// Differences from the virtual cell: no SUB and no poa (the cell polls command/la instead of taking notifications),
// and one extra CNT {run}p{i}/lux for the cell sensor.
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <utility>
#include <vector>
#include "cell_logic.h"

namespace m2m {

constexpr int ALL = 63, C = 1, R = 2, N = 16, DISC = 32;   // acop bits, as in zone.py
constexpr const char* ADMIN = "CAdmin";
constexpr const char* IN_CSI = "/tinyiot";
constexpr const char* OPEN_LEVEL = "org.onem2m.common.moduleclass.openLevel";

struct Req { std::string method, path, origin; int ty; std::string body; };

// Same mapping as zone.py: 0 closed .. 100 open = 100 cos^2(angle).
inline int openLevel(float disc) { double c = cos(disc * 3.14159265358979 / 180.0); return (int)lround(100 * c * c); }
inline float discFromSteps(long steps) { return discFromMotor(steps / STEPS_PER_DISC_DEG); }

inline std::string contentType(int ty) { return ty ? "application/json;ty=" + std::to_string(ty) : "application/json"; }
inline std::string url(const std::string& host, const std::string& cse, const std::string& path) {
  return host + "/" + cse + (path.empty() ? "" : "/" + path);
}

// Retry delay after n failures in a row: 1 s, 2 s, 4 s ... capped at 60 s.
inline uint32_t backoffMs(int fails) {
  if (fails <= 0) return 0;
  uint32_t ms = 1000UL << (fails > 7 ? 6 : fails - 1);
  return ms > 60000UL ? 60000UL : ms;
}

inline std::string q(const std::string& s) { return "\"" + s + "\""; }   // names here never hold quotes or backslashes
inline std::string escape(const std::string& s) {
  std::string o;
  for (char ch : s) { if (ch == '"' || ch == '\\') o += '\\'; o += ch; }
  return o;
}
inline std::string list(const std::vector<std::string>& v) {
  std::string o = "[";
  for (size_t k = 0; k < v.size(); k++) o += (k ? ", " : "") + q(v[k]);
  return o + "]";
}
inline std::vector<std::string> remote(const std::string& o) { return {o, std::string(IN_CSI) + "/" + o}; }
inline std::string fmt1(float v) { char b[24]; snprintf(b, sizeof b, "%.1f", v); return b; }

inline std::string cellRn(const std::string& run, int i) { return run + "p" + std::to_string(i); }
inline std::string cellOrig(const std::string& run, int i) { return "C" + cellRn(run, i); }
inline std::string envOrig(const std::string& run) { return "C" + run + "env"; }

// CIN holding a JSON content string, the way onem2m.Client.create() wraps it.
inline std::string cin(const std::string& content) { return "{\"m2m:cin\": {\"con\": " + q(escape(content)) + "}}"; }

// ACP owned by `owner`: owner all rights, controller C|R|N|DISC, viewer R|N|DISC (zone.py setup()).
inline Req acpReq(const std::string& run, const std::string& rn, const std::string& owner) {
  auto rule = [](const std::vector<std::string>& o, int op) { return "{\"acor\": " + list(o) + ", \"acop\": " + std::to_string(op) + "}"; };
  std::string body = "{\"m2m:acp\": {\"rn\": " + q(rn) + ", \"pv\": {\"acr\": [" + rule({owner}, ALL) + ", " +
                     rule(remote("C" + run + "ctl"), C | R | N | DISC) + ", " + rule(remote("C" + run + "view"), R | N | DISC) +
                     "]}, \"pvs\": {\"acr\": [" + rule({ADMIN}, ALL) + "]}}}";
  return {"POST", "", ADMIN, 1, body};
}
inline Req acpGetReq(const std::string& rn) { return {"GET", rn, ADMIN, 0, ""}; }   // ri of an ACP that already exists
inline std::vector<Req> acpReqs(const std::string& run, int i) {
  return {acpReq(run, run + "envacp", envOrig(run)), acpReq(run, cellRn(run, i) + "acp", cellOrig(run, i))};
}

inline std::string aeBody(const std::string& rn) {
  return "{\"m2m:ae\": {\"rn\": " + q(rn) + ", \"api\": \"Npolagrid\", \"rr\": false, \"srv\": [\"3\"]}}";
}
inline std::string cntBody(const std::string& rn, const std::string& acp, const std::string& lbl = "") {
  return "{\"m2m:cnt\": {\"rn\": " + q(rn) + ", \"mni\": 10, \"acpi\": [" + q(acp) + "]" +
         (lbl.empty() ? "" : ", \"lbl\": [" + q(lbl) + "]") + "}}";
}

// Everything after the ACPs, in creation order. A 409 (already there) counts as done, so a reboot repeats it safely.
// row/col: where the cell sits in the window, seen from inside (row 0 = top, col 0 = left). Put on the state as a second label
// "polagrid/<run>/pos/<row>/<col>" so the app draws each new cell where it was installed. -1 = not placed.
inline std::vector<Req> resourceReqs(const std::string& run, int i, const std::string& envAcp, const std::string& cellAcp,
                                     int row = -1, int col = -1) {
  std::string rn = cellRn(run, i), o = cellOrig(run, i), e = envOrig(run);
  std::string pos = row < 0 ? "" : ", " + q("polagrid/" + run + "/pos/" + std::to_string(row) + "/" + std::to_string(col));
  return {
      {"POST", "", e, 2, aeBody(run + "env")},
      {"POST", run + "env", e, 3, cntBody("sun", envAcp)},
      {"POST", run + "env", e, 3, cntBody("desks", envAcp)},
      {"POST", "", o, 2, aeBody(rn)},
      {"POST", rn, o, 3, cntBody("command", cellAcp, "polagrid/" + run + "/command")},
      {"POST", rn, o, 28, "{\"cod:opeLl\": {\"rn\": \"state\", \"cnd\": " + q(OPEN_LEVEL) + ", \"opeLl\": 100, \"minLl\": 0, "
                          "\"maxLl\": 100, \"acpi\": [" + q(cellAcp) + "], \"lbl\": [" + q("polagrid/" + run + "/state") + pos + "]}}"},
      {"POST", rn, o, 3, cntBody("lux", cellAcp)},
  };
}

inline Req pollReq(const std::string& run, int i) { return {"GET", cellRn(run, i) + "/command/la", cellOrig(run, i), 0, ""}; }
inline Req stateReq(const std::string& run, int i, int level) {
  return {"PUT", cellRn(run, i) + "/state", cellOrig(run, i), 0, "{\"cod:opeLl\": {\"opeLl\": " + std::to_string(level) + "}}"};
}
// Desk reading. cmd is the command id it answers, or "t<seconds>" for a periodic reading (as zone.py does).
inline Req desksReq(const std::string& run, const std::string& cmd, const std::vector<float>& lux) {
  std::string l;
  for (size_t k = 0; k < lux.size(); k++) l += (k ? ", " : "") + fmt1(lux[k]);
  return {"POST", run + "env/desks", envOrig(run), 4, cin("{\"cmd\": " + q(escape(cmd)) + ", \"lux\": [" + l + "]}")};
}
inline Req cellLuxReq(const std::string& run, int i, float lux) {
  return {"POST", cellRn(run, i) + "/lux", cellOrig(run, i), 4, cin("{\"lux\": " + fmt1(lux) + "}")};
}

// Value of the first string field `key` in a JSON text, unescaped. Enough for CSE replies; not a full JSON parser.
inline bool jsonString(const std::string& js, const char* key, std::string& out) {
  std::string k = std::string("\"") + key + "\"";
  size_t p = js.find(k);
  if (p == std::string::npos) return false;
  p += k.size();
  while (p < js.size() && (js[p] == ' ' || js[p] == ':')) p++;
  if (p >= js.size() || js[p] != '"') return false;
  out.clear();
  for (p++; p < js.size(); p++) {
    char ch = js[p];
    if (ch == '"') return true;
    if (ch == '\\') {
      if (++p >= js.size()) return false;
      ch = js[p];
      if (ch == 'n') ch = '\n'; else if (ch == 't') ch = '\t'; else if (ch == 'u') return false;   // CSE never sends \u here
    }
    out += ch;
  }
  return false;
}

// Which commands to apply. command/la still holds the last command the controller sent, maybe from hours ago, so the
// first one the cell sees after a reboot is stale: it is remembered, not applied (the cell stays open, its safe state),
// and the controller's heartbeat (a fresh command id every 10 min) brings it back. Anything newer than that is applied once.
struct CommandGate {
  std::string last;
  bool baselined = false;
  bool accept(const std::string& cmd) {
    if (!baselined) { baselined = true; last = cmd; return false; }
    if (cmd == last) return false;
    last = cmd;
    return true;
  }
  void noneYet() { baselined = true; }   // command/la answered 404: there is no old command, the first one that appears is new
};

// A command whose angle is not a number or lies outside 0..90 means the controller is confused: the cell opens instead.
inline bool angleSane(float a) { return std::isfinite(a) && a >= -0.5f && a <= 90.5f; }

// Fail-safe on a lost link: no reply from the CSE (any HTTP status counts) for LINK_LOST_MS. True once per outage.
constexpr uint32_t LINK_LOST_MS = 60000;
inline bool linkLost(uint32_t lastReplyMs, uint32_t nowMs, bool& reported) {
  if (nowMs - lastReplyMs <= LINK_LOST_MS) { reported = false; return false; }
  if (reported) return false;
  return reported = true;
}

// True when the command CIN says "mode": "privacy" (missing or anything else = auto). Same `con` unwrapping as below.
inline bool commandPrivacy(const std::string& body) {
  std::string con, mode;
  if (!jsonString(body, "con", con)) con = body;
  return jsonString(con, "mode", mode) && mode == "privacy";
}

// Reply of GET command/la: {"m2m:cin": {"con": "{\"cmd\": \"r1c3\", \"angles\": [45.0, ...]}", ...}}.
// Takes this cell's entry angles[i]. False on anything malformed, so a bad command is never applied.
inline bool parseCommandCin(const std::string& body, int i, std::string& cmd, float& angle) {
  std::string con;
  // tinyIoT returns `con` as a JSON object (not a string) for CINs read back from its DB after a restart
  if (!jsonString(body, "con", con)) con = body;
  if (!jsonString(con, "cmd", cmd) || cmd.empty()) return false;
  size_t p = con.find("\"angles\"");
  if (p == std::string::npos || (p = con.find('[', p)) == std::string::npos) return false;
  const char* s = con.c_str() + p + 1;
  for (int k = 0; k < i; k++) {
    s = strchr(s, ',');
    if (!s) return false;
    s++;
  }
  char* end;
  double v = strtod(s, &end);
  if (end == s || !isfinite(v)) return false;
  while (*end == ' ') end++;
  if (*end != ',' && *end != ']') return false;
  angle = (float)v;
  return true;
}

// ---- oneM2M over MQTT (see the MQTT design notes) ----

// Request primitive: op 1/2/3 = create/retrieve/update, rvi is the STRING "3" (tinyIoT reads valuestring), ty only for create,
// pc only when there is a body. `to` is the CSE name plus the HTTP path.
inline std::string primitive(const std::string& cse, const Req& r, const std::string& rqi) {
  int op = r.method == "POST" ? 1 : r.method == "PUT" ? 3 : 2;
  return "{\"op\": " + std::to_string(op) + ", \"to\": " + q(cse + (r.path.empty() ? "" : "/" + r.path)) + ", \"fr\": " + q(r.origin) +
         ", \"rqi\": " + q(rqi) + ", \"rvi\": \"3\"" + (op == 1 ? ", \"ty\": " + std::to_string(r.ty) : "") +
         (r.body.empty() ? "" : ", \"pc\": " + r.body) + "}";
}

inline std::string reqTopic(const std::string& origin, const std::string& cseRi) {   // a '/' in an originator becomes ':' as in tinyIoT
  std::string o = origin;
  for (auto& ch : o) if (ch == '/') ch = ':';
  return "/oneM2M/req/" + o + "/" + cseRi + "/json";
}
inline std::string respFilter(const std::string& cseRi) { return "/oneM2M/resp/+/" + cseRi + "/json"; }
inline std::string notifyTopic(const std::string& cseRi) { return "/oneM2M/req/" + cseRi + "/+/json"; }   // 3rd level = the cell
// True when an MQTT topic is for this cell (design 2-2, 3-2): resp/<our originator>/<cse>/json or req/<cse>/<cell originator>/json.
// Anything else (another run, another CSE, a bad shape) is not ours. The resp originator may be the cell, env or CAdmin; rqi settles the rest.
inline bool topicForMe(const std::string& topic, const std::string& cseRi, const std::string& run, int i) {
  std::string s[7];
  int n = 0;
  for (size_t b = 0; n < 7;) {
    size_t e = topic.find('/', b);
    s[n++] = topic.substr(b, e == std::string::npos ? e : e - b);
    if (e == std::string::npos) break;
    b = e + 1;
  }
  if (n != 6 || !s[0].empty() || s[1] != "oneM2M" || s[5] != "json") return false;
  if (s[2] == "resp") return s[4] == cseRi && (s[3] == cellOrig(run, i) || s[3] == envOrig(run) || s[3] == ADMIN);
  return s[2] == "req" && s[3] == cseRi && s[4] == cellOrig(run, i);
}
// nu of the SUB: host must be the same string as the MN's MQTT_HOST:port so tinyIoT reuses its connection (design 2-2)
inline std::string nuFor(const std::string& hostPort, const std::string& origin) { return "mqtt://" + hostPort + "/" + origin + "/json"; }

inline Req subReq(const std::string& run, int i, const std::string& nu) {
  return {"POST", cellRn(run, i) + "/command", cellOrig(run, i), 23,
          "{\"m2m:sub\": {\"rn\": \"s\", \"nu\": [" + q(nu) + "], \"enc\": {\"net\": [3]}, \"nct\": 1}}"};
}
inline Req subNuReq(const std::string& run, int i, const std::string& nu) {   // the SUB exists (409): make sure nu is ours
  return {"PUT", cellRn(run, i) + "/command/s", cellOrig(run, i), 0, "{\"m2m:sub\": {\"nu\": [" + q(nu) + "]}}"};
}

// Integer value of the first `key` in a JSON text (rsc). Not a full parser, same as jsonString.
inline bool jsonInt(const std::string& js, const char* key, int& out) {
  std::string k = std::string("\"") + key + "\"";
  size_t p = js.find(k);
  if (p == std::string::npos) return false;
  p += k.size();
  while (p < js.size() && (js[p] == ' ' || js[p] == ':')) p++;
  char* end;
  long v = strtol(js.c_str() + p, &end, 10);
  if (end == js.c_str() + p) return false;
  out = (int)v;
  return true;
}
// rsc to the HTTP code send() returns (design 2-6); anything not in the table is 500.
inline int httpCode(int rsc) {
  switch (rsc) {
    case 2000: case 2004: return 200;
    case 2001: return 201;
    case 4004: return 404;
    case 4103: return 403;
    case 4105: return 409;
    default: return 500;
  }
}
// True when js answers request `rqi` (a late reply to an earlier request has another rqi and is refused); code = HTTP code.
inline bool matchResponse(const std::string& js, const std::string& rqi, int& code) {
  std::string got;
  int rsc;
  if (!jsonString(js, "rqi", got) || got != rqi || !jsonInt(js, "rsc", rsc)) return false;
  code = httpCode(rsc);
  return true;
}

// esp-mqtt cuts a big message into MQTT_EVENT_DATA pieces (total_data_len, current_data_offset). add() takes one piece and
// returns true once, with the whole text in `out`. A gap, a restart without offset 0 or a total above MAX drops the message.
struct Reassembly {
  static constexpr int MAX = 8192;
  std::string buf;
  bool ok = false;
  bool add(const char* d, int len, int total, int offset, std::string& out) {
    if (offset == 0) { buf.clear(); ok = total <= MAX && total >= len; }
    else if (!ok || (size_t)offset != buf.size() || (size_t)(offset + len) > (size_t)total) ok = false;
    if (!ok) { buf.clear(); return false; }
    buf.append(d, len);
    if ((int)buf.size() < total) return false;
    out.swap(buf);
    buf.clear();
    ok = false;
    return true;
  }
};

}  // namespace m2m
