#!/usr/bin/env bash
# Record one simulated day at 10-minute steps for the replay (replay/day_10min.jsonl). Takes about 25 to 30 minutes and loads the CPU
# (10 zones of 100 cells over the CSE). The zones run at speed 0.05 (20 s per step) because reading all 1,000 cells takes about 10 s under
# that load; at 1x the recorder would miss most steps (docs 0-4). Run in WSL from sw/app_ui/demo/:  bash record_day.sh
D=$(cd "$(dirname "$0")" && pwd)
TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(6))"); export DEMO_TOKEN=$TOKEN
bash "$D/demo_down.sh" quiet
SERVE=--serve SLOW=--slow bash "$D/run_zones.sh" 10 10 </dev/null || exit 1
mkdir -p "$D/replay"; rm -f "$D/replay/rec_slow.jsonl"
cd "$D" && setsid nohup python3 -u server.py --live --mns 10 --interval 1 --record replay/rec_slow.jsonl > /tmp/demo_srv.log 2>&1 < /dev/null &
for i in $(seq 60); do ss -ltn | grep -q ":8000 " && break; sleep 1; done
post() { curl -s -o /dev/null -X POST -H "X-Demo-Token: $TOKEN" -H 'Content-Type: application/json' -d "$1" localhost:8000/api/ctl; }
post '{"speed":0.05}'; post '{"running":true}'
for i in $(seq 360); do   # up to 30 minutes
  t=$(curl -s localhost:8000/api/frame | python3 -c 'import json,sys;print(json.load(sys.stdin).get("t","")[11:16])' 2>/dev/null)
  echo "$(date +%T) sim $t"; [ "$t" \> "18:40" ] && break; sleep 5
done
bash "$D/demo_down.sh" quiet
python3 "$D/make_replay10.py" "$D/replay/rec_slow.jsonl" "$D/replay/day_10min.jsonl"
