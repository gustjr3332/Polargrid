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
  assert(res[5].body.find("pos/") == std::string::npos);   // no position given, no position label
  auto placed = resourceReqs(run, 1, "A1", "A2", 2, 3);
  assert(placed[5].body.find("\"lbl\": [\"polagrid/real1/state\", \"polagrid/real1/pos/2/3\"]") != std::string::npos);
  assert(res[5].ty == 28 && res[5].body.find("\"acpi\": [\"A2\"]") != std::string::npos);

  // an old command left on the CSE is not applied after a reboot; later ones are, each once
  CommandGate gate;
  assert(!gate.accept("real1c9"));                    // first sight after boot = stale
  assert(!gate.accept("real1c9"));                    // still the same one
  assert(gate.accept("real1c10") && !gate.accept("real1c10"));
  CommandGate fresh;
  fresh.noneYet();                                    // 404 before any command: the first one counts
  assert(fresh.accept("real1c1"));

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

  // privacy mode rides in the command CIN as "mode"; missing or any other value is auto
  assert(commandPrivacy("{\"m2m:cin\": {\"con\": \"{\\\"cmd\\\": \\\"p1\\\", \\\"angles\\\": [90.0], \\\"mode\\\": \\\"privacy\\\"}\"}}"));
  assert(commandPrivacy("{\"m2m:cin\": {\"con\": {\"cmd\": \"p2\", \"angles\": [90.0], \"mode\": \"privacy\"}}}"));   // object-form con
  assert(!commandPrivacy(la) && !commandPrivacy("{\"m2m:cin\": {\"con\": \"{\\\"cmd\\\": \\\"a\\\", \\\"angles\\\": [5], \\\"mode\\\": \\\"auto\\\"}\"}}"));

  // nonsense angles and a silent link are the cell's own reasons to open
  assert(angleSane(0) && angleSane(90) && angleSane(-0.4f) && angleSane(90.4f));
  assert(!angleSane(-1) && !angleSane(91) && !angleSane(NAN) && !angleSane(INFINITY));
  bool rep = false;
  assert(!linkLost(1000, 1000 + LINK_LOST_MS, rep));                         // exactly at the limit: still fine
  assert(linkLost(1000, 1001 + LINK_LOST_MS, rep) && rep);
  assert(!linkLost(1000, 2000 + LINK_LOST_MS, rep));                         // reported once per outage
  assert(!linkLost(90000, 90500, rep) && !rep);                              // a reply ends the outage, the next one reports again
  assert(linkLost(90000, 90001 + LINK_LOST_MS, rep));

  // ---- MQTT binding. Shapes checked against the 11-11 capture (results/mqtt_stage1_1111.txt): rsc is a number, rqi a string,
  // "to" is accepted as "<CSEBase rn>[/path]" or "<CSE-RI>" and refused with a leading "/" or "~/" ----
  // exact primitives: create (ty, pc), retrieve (no ty, no pc), update (no ty, pc), CSE base (empty path)
  assert(primitive("TinyIoT-mn001", {"POST", "real1p0", "Creal1p0", 3, "{\"m2m:cnt\": {\"rn\": \"lux\"}}"}, "esp1") ==
         "{\"op\": 1, \"to\": \"TinyIoT-mn001/real1p0\", \"fr\": \"Creal1p0\", \"rqi\": \"esp1\", \"rvi\": \"3\", \"ty\": 3, "
         "\"pc\": {\"m2m:cnt\": {\"rn\": \"lux\"}}}");
  assert(primitive("TinyIoT-mn001", pollReq(run, 0), "esp2") ==
         "{\"op\": 2, \"to\": \"TinyIoT-mn001/real1p0/command/la\", \"fr\": \"Creal1p0\", \"rqi\": \"esp2\", \"rvi\": \"3\"}");
  assert(primitive("TinyIoT-mn001", stateReq(run, 0, 50), "esp3") ==
         "{\"op\": 3, \"to\": \"TinyIoT-mn001/real1p0/state\", \"fr\": \"Creal1p0\", \"rqi\": \"esp3\", \"rvi\": \"3\", "
         "\"pc\": {\"cod:opeLl\": {\"opeLl\": 50}}}");
  assert(primitive("TinyIoT-mn001", {"GET", "", "CAdmin", 0, ""}, "x").find("\"to\": \"TinyIoT-mn001\"") != std::string::npos);

  // topics: /oneM2M/{req|resp}/a/b/json
  assert(reqTopic("Creal1p0", "id-mn001") == "/oneM2M/req/Creal1p0/id-mn001/json");
  assert(reqTopic("/tinyiot/Cx", "id-mn001") == "/oneM2M/req/:tinyiot:Cx/id-mn001/json");
  assert(respFilter("id-mn001") == "/oneM2M/resp/+/id-mn001/json");
  assert(notifyTopic("id-mn001") == "/oneM2M/req/id-mn001/+/json");
  assert(topicForMe("/oneM2M/req/id-mn001/Creal1p0/json", "id-mn001", "real1", 0));      // our SUB notification
  assert(topicForMe("/oneM2M/resp/Creal1p0/id-mn001/json", "id-mn001", "real1", 0));     // our reply
  assert(topicForMe("/oneM2M/resp/Creal1env/id-mn001/json", "id-mn001", "real1", 0));
  assert(topicForMe("/oneM2M/resp/CAdmin/id-mn001/json", "id-mn001", "real1", 0));
  assert(!topicForMe("/oneM2M/req/id-mn001/Creal2p0/json", "id-mn001", "real1", 0));     // another run
  assert(!topicForMe("/oneM2M/req/id-mn001/Creal1p1/json", "id-mn001", "real1", 0));     // another cell
  assert(!topicForMe("/oneM2M/resp/Creal2p0/id-mn001/json", "id-mn001", "real1", 0));
  assert(!topicForMe("/oneM2M/req/id-mn002/Creal1p0/json", "id-mn001", "real1", 0));     // another CSE
  assert(!topicForMe("/oneM2M/req/id-mn001/Creal1p0", "id-mn001", "real1", 0));          // malformed
  assert(!topicForMe("/oneM2M/req/id-mn001/Creal1p0/json/x", "id-mn001", "real1", 0));
  assert(!topicForMe("oneM2M/req/id-mn001/Creal1p0/json", "id-mn001", "real1", 0));
  assert(!topicForMe("/oneM2M/reg/id-mn001/Creal1p0/json", "id-mn001", "real1", 0));
  assert(!topicForMe("", "id-mn001", "real1", 0));
  assert(nuFor("127.0.0.1:1883", "Creal1p0") == "mqtt://127.0.0.1:1883/Creal1p0/json");
  assert(subReq(run, 0, "mqtt://127.0.0.1:1883/Creal1p0/json").body ==
         "{\"m2m:sub\": {\"rn\": \"s\", \"nu\": [\"mqtt://127.0.0.1:1883/Creal1p0/json\"], \"enc\": {\"net\": [3]}, \"nct\": 1}}");
  assert(subReq(run, 0, "n").ty == 23 && subReq(run, 0, "n").path == "real1p0/command");
  assert(subNuReq(run, 0, "n").method == "PUT" && subNuReq(run, 0, "n").path == "real1p0/command/s" &&
         subNuReq(run, 0, "n").body == "{\"m2m:sub\": {\"nu\": [\"n\"]}}");

  // responses: rsc to HTTP code, and a late reply (other rqi) is refused
  assert(httpCode(2000) == 200 && httpCode(2004) == 200 && httpCode(2001) == 201 && httpCode(4004) == 404 &&
         httpCode(4103) == 403 && httpCode(4105) == 409 && httpCode(5000) == 500 && httpCode(4000) == 500);
  int code = 0;
  const char* resp = "{\"rsc\": 2001, \"rqi\": \"esp7\", \"rvi\": \"3\", \"pc\": {\"m2m:acp\": {\"ri\": \"3-9\"}}}";
  assert(matchResponse(resp, "esp7", code) && code == 201);
  code = 0;
  assert(!matchResponse(resp, "esp8", code) && code == 0);                  // late reply to esp7 while waiting for esp8
  assert(!matchResponse("{\"rsc\": 2000}", "esp7", code));                  // no rqi
  assert(!matchResponse("{\"rqi\": \"esp7\"}", "esp7", code));              // no rsc
  assert(matchResponse("{\"rsc\":4105,\"rqi\":\"esp7\"}", "esp7", code) && code == 409);

  // 3 pieces make one message exactly once; a gap, a message that does not start at 0 and a too big total are dropped
  Reassembly re;
  std::string whole, msg = "0123456789abcdefghij";
  assert(!re.add(msg.data(), 8, 20, 0, whole) && !re.add(msg.data() + 8, 8, 20, 8, whole));
  assert(re.add(msg.data() + 16, 4, 20, 16, whole) && whole == msg);
  assert(!re.add(msg.data() + 16, 4, 20, 16, whole));                       // a stray repeat of the last piece
  assert(re.add(msg.data(), 20, 20, 0, whole) && whole == msg);             // single piece
  assert(!re.add(msg.data(), 8, 20, 0, whole) && !re.add(msg.data() + 12, 8, 20, 12, whole));   // gap: piece at 8 missing
  assert(!re.add(msg.data() + 8, 8, 20, 8, whole) && !re.add(msg.data() + 16, 4, 20, 16, whole));   // and the rest stays dead
  assert(!re.add(msg.data(), 8, Reassembly::MAX + 1, 0, whole) && !re.add(msg.data() + 8, 12, Reassembly::MAX + 1, 8, whole));
  assert(re.add(msg.data(), 20, 20, 0, whole));                             // a new message starts clean after a drop

  // notification (sgn with the CIN) goes through parseCommandCin; the SUB verification (vrq) has no cmd and is refused
  // shapes below are from the 11-11 stage-1 capture (results/mqtt_stage1_1111.txt): sgn is published bare, no pc/rqi wrapper,
  // sur is "/<CSE-RI>/<sub ri>", and the vrq message arrives before the SUB response
  const char* sgn = "{\"m2m:sgn\":{\"nev\":{\"net\":3,\"rep\":{\"m2m:cin\":{\"con\":\"{\\\"cmd\\\": \\\"real1c7\\\", "
                    "\\\"angles\\\": [33.0]}\",\"ty\":4,\"ct\":\"20261111T022836,339\",\"ri\":\"4-20261111T022836,3390032\","
                    "\"rn\":\"4-20261111T022836,3390032\",\"lt\":\"20261111T022836,339\",\"pi\":\"3-20261111T022514,0570012\","
                    "\"et\":\"20281110T022836,339\",\"cs\":43,\"st\":3}}},\"sur\":\"/id-mn001/23-20261111T022614,0750027\"}}";
  assert(parseCommandCin(sgn, 0, cmd, a) && cmd == "real1c7" && a == 33.0f);
  assert(!parseCommandCin("{\"m2m:sgn\":{\"cr\":\"Creal1p0\",\"sur\":\"/id-mn001/23-20261111T022614,0750027\",\"vrq\":true}}", 0, cmd, a));

  // notification first, then the boot-time la with the same command: applied once. A 404 la never blocks the first notification
  CommandGate g2;
  g2.noneYet();                                                             // main.cpp calls this before accept() on the notification path
  assert(g2.accept("real1c7"));
  assert(!g2.accept("real1c7"));                                            // la at boot answers with the same cmd
  assert(g2.accept("real1c8"));                                             // the next command still passes

  // the angle goes through the same serial parser path as a typed command
  Cells c;
  char line[32];
  snprintf(line, sizeof line, "A %d %.1f", 0, 45.0f);
  assert(parseCommand(line, c, 10) == Result::Ok && c.disc[0] == 45.0f && c.lastCmdMs == 10);
  puts("all tests passed");
}
