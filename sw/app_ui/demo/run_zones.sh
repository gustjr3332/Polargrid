#!/usr/bin/env bash
# Start M fresh zones of 10x10 cells (one MN each) and run one simulated day in each, so /flow has traffic to show.
# Usage (inside WSL): [SERVE=--serve] bash run_zones.sh [M=10] [STEP_MIN=5]. SERVE=--serve waits for Start from the demo page (/api/ctl). Moves the old MN databases to ~/polargrid/db_backup/ (tools/fresh_mn.sh).
# Writes runs.json for server.py when every zone has finished its setup. Zones run in the background; logs in /tmp/z<k>.log.
M=${1:-10}; STEP=${2:-5}
D=$(cd "$(dirname "$0")" && pwd); E=$D/../../edge_ai
cd "$E" && bash tools/run_in.sh >/dev/null && bash tools/fresh_mn.sh "$M" >/dev/null
for i in $(seq 90); do [ "$(ss -ltn | grep -cE ":(30(0[1-9]|[1-9][0-9])) ")" -ge "$M" ] && break; sleep 1; done
for k in $(seq "$M"); do
  setsid nohup python3 -u -m polagrid.closed_loop --host http://127.0.0.1:$((3000+k)) --cse TinyIoT-mn$(printf %03d "$k") \
    --rows 10 --cols 10 --controller online --step "$STEP" --port $((9500+10*k)) $SERVE > /tmp/z$k.log 2>&1 < /dev/null &
done
for i in $(seq 120); do [ "$(grep -l '^\[setup\]' /tmp/z{1..10}.log 2>/dev/null | wc -l)" -ge "$M" ] && break; sleep 1; done
python3 - "$M" "$D/runs.json" <<'PY'
import json, re, sys
m = int(sys.argv[1])
json.dump({str(k): re.search(r"run (r\d+)", open(f"/tmp/z{k}.log").read())[1] for k in range(1, m + 1)}, open(sys.argv[2], "w"))
PY
echo "zones started; runs.json written"
