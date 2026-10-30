#!/usr/bin/env bash
# IN outage test (WSL, from sw/edge_ai): fake cell fk1 + controller on mn001, kill the IN, restart it. Usage: bash tools/run_in_outage.sh [base_s] [outage_s] [recover_s]
# Refuses to run if an IN or MN is already up (a demo stack must not be touched).
B=${1:-150}; O=${2:-240}; R=${3:-120}
cd "$(dirname "$0")/.." || exit 1
D=${TAGDAY:-$(date +%m%d)}; OUT=results/in_outage_$D; : > $OUT.events.log
ss -ltn | grep -qE ":(3000|3001) " && { echo "IN/MN already running, abort"; exit 1; }
ev() { echo "$(date +%s.%N) $1" | tee -a $OUT.events.log; }
in_pid() { for p in $(pgrep -x server); do [ "$(readlink /proc/$p/cwd)" = "$HOME/polargrid/in_nolock" ] && echo $p; done; }
csr() { curl -s -H 'X-M2M-Origin: CAdmin' -H 'X-M2M-RI: c1' -H 'X-M2M-RVI: 3' -H 'Accept: application/json' "http://127.0.0.1:3000/tinyiot?fu=1&ty=16" -m 5; echo; }
bash tools/run_in.sh; bash ~/polargrid/nodes.sh start 1; sleep 5
ev "CSR_BEFORE $(csr)"
python3 -u tools/fake_cell.py --run fk1 > $OUT.fakecell.log 2>&1 & FAKE=$!
sleep 8
python3 tools/in_outage.py --run fk1 --csv $OUT.csv --duration $((B+O+R)) > $OUT.driver.log 2>&1 & DRV=$!
sleep $B; ev "IN_STOP"; kill $(in_pid); sleep 1; ev "IN_DOWN_CHECK $(ss -ltn | grep -c ':3000 ') listeners; mn001 alive: $(ss -ltn | grep -c ':3001 ')"
sleep $O; ev "IN_START"; bash tools/run_in.sh >> $OUT.events.log 2>&1
sleep 20; ev "CSR_AFTER_RESTART_20s $(csr)"
sleep $((R-20)); ev "CSR_END $(csr)"
wait $DRV; ev "DRIVER_EXIT $?"
kill $FAKE
cp ~/polargrid/nodes/mn001/server.log $OUT.mn001.log; cp /tmp/in.log $OUT.in.log
bash ~/polargrid/nodes.sh stop; kill $(in_pid); sleep 1; ev "CLEANED"
