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
inline float discFromSteps(long steps) { return steps / STEPS_PER_DISC_DEG; }

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
inline std::vector<Req> resourceReqs(const std::string& run, int i, const std::string& envAcp, const std::string& cellAcp) {
  std::string rn = cellRn(run, i), o = cellOrig(run, i), e = envOrig(run);
  return {
      {"POST", "", e, 2, aeBody(run + "env")},
      {"POST", run + "env", e, 3, cntBody("sun", envAcp)},
      {"POST", run + "env", e, 3, cntBody("desks", envAcp)},
      {"POST", "", o, 2, aeBody(rn)},
      {"POST", rn, o, 3, cntBody("command", cellAcp, "polagrid/" + run + "/command")},
      {"POST", rn, o, 28, "{\"cod:opeLl\": {\"rn\": \"state\", \"cnd\": " + q(OPEN_LEVEL) + ", \"opeLl\": 100, \"minLl\": 0, "
                          "\"maxLl\": 100, \"acpi\": [" + q(cellAcp) + "], \"lbl\": [" + q("polagrid/" + run + "/state") + "]}}"},
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

// Reply of GET command/la: {"m2m:cin": {"con": "{\"cmd\": \"r1c3\", \"angles\": [45.0, ...]}", ...}}.
// Takes this cell's entry angles[i]. False on anything malformed, so a bad command is never applied.
inline bool parseCommandCin(const std::string& body, int i, std::string& cmd, float& angle) {
  std::string con;
  if (!jsonString(body, "con", con) || !jsonString(con, "cmd", cmd) || cmd.empty()) return false;
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

}  // namespace m2m
