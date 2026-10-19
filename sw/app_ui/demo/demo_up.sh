#!/usr/bin/env bash
# One command to start the 11/4 demo stack inside WSL, and a fresh database every time (a database with many old resources
# was slow: docs 0-8 #9). Stop everything with demo_down.sh, check it with preflight.sh.
#
#   bash demo_up.sh real            # the real cell (or tools/fake_cell.py): IN, one fresh MN, narrowed defaultACP, real_cell.py app, demo server
#   bash demo_up.sh virtual [M=10]  # M virtual zones of 100 cells (1,000 cells): fresh MNs, narrowed defaultACP, zones, demo server (waits for Start)
#   bash demo_up.sh replay          # no CSE: the recorded day (replay/live_1017.jsonl)
#
# real and virtual both use MN 1 and wipe its database, so run only one of them at a time (the two are shown separately).
# The demo page / phone app is then at http://localhost:8000/ (virtual, replay) or http://localhost:8000/mockup/?live=1 (real).
D=$(cd "$(dirname "$0")" && pwd); E=$D/../../edge_ai
MODE=${1:-real}; M=${2:-10}; RUN=${RUN:-real1}
TOKEN=${DEMO_TOKEN:-$(python3 -c "import secrets;print(secrets.token_urlsafe(6))")}   # every POST of the page needs it, so nobody else on the Wi-Fi can move the cells
export DEMO_TOKEN=$TOKEN
bash "$D/demo_down.sh" quiet
cd "$E" || exit 1
case "$MODE" in
  real)
    bash tools/run_in.sh >/tmp/run_in.out 2>&1 </dev/null && bash tools/fresh_mn.sh 1 >/tmp/fresh_mn.out 2>&1 </dev/null   # no inherited pipes: a caller piping our output must not wait for the servers
    for i in $(seq 30); do ss -ltn | grep -q ":3001 " && break; sleep 1; done
    python3 tools/harden_acp.py || { echo "harden_acp failed: MN 1 is up but its defaultACP is still wide open"; exit 1; }
    setsid nohup python3 -u tools/real_cell.py --run "$RUN" app > /tmp/real_cell.log 2>&1 < /dev/null &
    cd "$D" && setsid nohup python3 -u server.py --live --mns 1 --real "$RUN" > /tmp/demo_srv.log 2>&1 < /dev/null &
    echo "real: up. Start the cell (ESP32, or: python3 tools/fake_cell.py --run $RUN) and open http://localhost:8000/mockup/?live=1&token=$TOKEN"
    echo "      phone on the same Wi-Fi: run demo/phone_proxy.ps1 in an admin PowerShell, then open http://<PC Wi-Fi IP>:8000/mockup/?live=1&token=$TOKEN"
    ;;
  virtual)
    SERVE=--serve bash "$D/run_zones.sh" "$M" 10 </dev/null || exit 1       # fresh MNs, narrows defaultACP, starts the zones, writes runs.json
    cd "$D" && setsid nohup python3 -u server.py --live --mns "$M" --interval 1 > /tmp/demo_srv.log 2>&1 < /dev/null &
    echo "virtual: $M zones up, they wait for Start. Open http://localhost:8000/?token=$TOKEN and press Start. Fallback: bash demo_up.sh replay"
    ;;
  replay)
    REC=replay/day_10min.jsonl; [ -f "$D/$REC" ] || REC=replay/live_1017.jsonl   # exact 10-minute frames if recorded (record_day.sh)
    cd "$D" && setsid nohup python3 -u server.py --replay "$REC" --interval 1 > /tmp/demo_srv.log 2>&1 < /dev/null &
    echo "replay: open http://localhost:8000/?token=$TOKEN (plays the recorded day when the page connects; the speed select has 1x, 2x, 5x)"
    ;;
  *) echo "usage: bash demo_up.sh real | virtual [M] | replay"; exit 2 ;;
esac
for i in $(seq 40); do ss -ltn | grep -q ":8000 " && break; sleep 1; done   # discovery of 10 MNs comes before the server listens
ss -ltn | grep -q ":8000 " && echo "demo server on :8000" || { echo "demo server did not start, see /tmp/demo_srv.log"; exit 1; }
