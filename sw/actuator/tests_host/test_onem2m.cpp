// g++ -std=c++17 -I src tests_host/test_onem2m.cpp -o test_onem2m && ./test_onem2m
// ./test_onem2m --print prints the requests of one setup and one command cycle as "METHOD path origin ty body",
// the format of the zone.py capture in the README, so the two can be diffed line by line.
#include <cassert>
#include <cstdio>
#include <cstring>
#include "onem2m_logic.h"

using namespace m2m;

static void print(const Req& r) { printf("%s %s %s %d %s\n", r.method.c_str(), r.path.c_str(), r.origin.c_str(), r.ty, r.body.c_str()); }

int main(int argc, char** argv) {
  const std::string run = "real1";
  if (argc > 1 && !strcmp(argv[1], "--print")) {
    for (auto& r : acpReqs(run, 0)) print(r);
    for (auto& r : resourceReqs(run, 0, "RI-real1envacp", "RI-real1p0acp")) print(r);
    print(pollReq(run, 0));
    print(stateReq(run, 0, openLevel(45)));
    print(desksReq(run, "real1c1", {15.1f}));
    print(cellLuxReq(run, 0, 812.0f));
    return 0;
  }

  // opeLl mapping (zone.py: round(100 cos^2)) and back from the stepper position
  assert(openLevel(0) == 100 && openLevel(90) == 0 && openLevel(45) == 50 && openLevel(30) == 75 && openLevel(60) == 25);
  assert(openLevel(discFromSteps(stepsFromDisc(45))) == 50 && openLevel(discFromSteps(stepsFromDisc(12.3f))) == 95);

  assert(url("http://h:3001", "TinyIoT-mn001", "") == "http://h:3001/TinyIoT-mn001");
  assert(url("http://h:3001", "TinyIoT-mn001", "real1p0/state") == "http://h:3001/TinyIoT-mn001/real1p0/state");
  assert(contentType(0) == "application/json" && contentType(28) == "application/json;ty=28");

  assert(backoffMs(0) == 0 && backoffMs(1) == 1000 && backoffMs(2) == 2000 && backoffMs(6) == 32000);
  assert(backoffMs(7) == 60000 && backoffMs(100) == 60000);

  // exact bodies, same bytes as json.dumps in zone.py (captured in tests_host/zone_requests.txt)
  assert(stateReq(run, 0, 50).body == "{\"cod:opeLl\": {\"opeLl\": 50}}");
  assert(desksReq(run, "real1c1", {15.1f, 2.0f}).body ==
         "{\"m2m:cin\": {\"con\": \"{\\\"cmd\\\": \\\"real1c1\\\", \\\"lux\\\": [15.1, 2.0]}\"}}");
  assert(desksReq(run, "t5", {}).path == "real1env/desks" && desksReq(run, "t5", {}).origin == "Creal1env");
  auto res = resourceReqs(run, 0, "A1", "A2");
  assert(res.size() == 7 && res[4].body.find("\"lbl\": [\"polagrid/real1/command\"]") != std::string::npos);
  assert(res[5].ty == 28 && res[5].body.find("\"acpi\": [\"A2\"]") != std::string::npos);

  // ri of an ACP reply (create 201 or retrieve 200)
  std::string ri;
  assert(jsonString("{\"m2m:acp\":{\"rn\":\"real1p0acp\",\"ri\":\"3-2026\",\"pi\":\"x\"}}", "ri", ri) && ri == "3-2026");
  assert(!jsonString("{\"m2m:acp\":{}}", "ri", ri));

  // command CIN, as tinyIoT returns it for GET command/la (compact) and with spaces
  std::string cmd; float a = -1;
  const char* la = "{\"m2m:cin\":{\"rn\":\"4-1\",\"ty\":4,\"con\":\"{\\\"cmd\\\": \\\"real1c1\\\", \\\"angles\\\": [45.0]}\",\"cs\":36}}";
  assert(parseCommandCin(la, 0, cmd, a) && cmd == "real1c1" && a == 45.0f);
  assert(!parseCommandCin(la, 1, cmd, a));                                    // no entry for cell 1
  const char* many = "{\"m2m:cin\": {\"con\": \"{\\\"cmd\\\": \\\"r9c2\\\", \\\"angles\\\": [0.0, 12.5, 90.0]}\"}}";
  assert(parseCommandCin(many, 1, cmd, a) && cmd == "r9c2" && a == 12.5f);
  assert(parseCommandCin(many, 2, cmd, a) && a == 90.0f);
  assert(!parseCommandCin(many, 3, cmd, a));
  float keep = a;
  assert(!parseCommandCin("{\"m2m:cin\": {\"con\": \"{\\\"cmd\\\": \\\"x\\\", \\\"angles\\\": [abc]}\"}}", 0, cmd, a) && a == keep);
  assert(!parseCommandCin("{\"m2m:cin\": {\"con\": \"{\\\"angles\\\": [1]}\"}}", 0, cmd, a));   // no cmd id
  assert(parseCommandCin("{\"m2m:cin\": {\"con\": {\"cmd\": \"r5c1\", \"angles\": [33.5]}}}", 0, cmd, a) && cmd == "r5c1" && a == 33.5f);   // object-form con
  assert(!parseCommandCin("{\"m2m:dbg\": \"resource does not exist\"}", 0, cmd, a));
  assert(!parseCommandCin("{\"m2m:cin\": {\"con\": \"{\\\"cmd\\\": \\\"x\\\", \\\"angles\\\": [1", 0, cmd, a));   // cut off

  // the angle goes through the same serial parser path as a typed command
  Cells c;
  char line[32];
  snprintf(line, sizeof line, "A %d %.1f", 0, 45.0f);
  assert(parseCommand(line, c, 10) == Result::Ok && c.disc[0] == 45.0f && c.lastCmdMs == 10);
  puts("all tests passed");
}
