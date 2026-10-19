#!/usr/bin/env bash
# Check the demo before going on stage. Prints OK / WARN / FAIL lines, exit 1 on FAIL.
#   bash preflight.sh [M]      M = number of MNs that should be up (1 for the real cell, 10 for the virtual 1,000 cells)
M=${1:-10}; D=$(cd "$(dirname "$0")" && pwd); E=$D/../../edge_ai; bad=0
say() { echo "$1  $2"; if [ "$1" = FAIL ]; then bad=1; fi; return 0; }
ss -ltn | grep -q ":3000 " && say OK "IN on :3000" || say FAIL "IN is not running (bash demo_up.sh ...)"
up=$(ss -ltn | grep -cE ":(30(0[1-9]|[1-9][0-9])) "); [ "$up" -ge "$M" ] && say OK "$up MN(s) listening (need $M)" || say FAIL "only $up of $M MNs listening"
ss -ltn | grep -q ":1883 " && say OK "mosquitto :1883" || say WARN "mosquitto not listening (MN MQTT needs it)"
ss -ltn | grep -q ":8000 " && say OK "demo server :8000" || say FAIL "demo server not running"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{}" localhost:8000/api/ctl)
[ "$code" = 401 ] && say OK "POST without the token is refused (401)" || say WARN "POST without a token gave $code: the server runs without --token (replay mode has no controls)"
big=$(find ~/polargrid/nodes -name data.db -size +100M 2>/dev/null | wc -l)
[ "$big" -eq 0 ] && say OK "no MN database over 100 MB (the rule is a fresh database: demo_up.sh does it)" || say WARN "$big MN database(s) over 100 MB: restart with demo_up.sh"
(cd "$E" && python3 tools/harden_acp.py --mns "$M" --check >/tmp/harden.out 2>&1) && say OK "defaultACP has no wildcard on $M MN(s)" || say FAIL "defaultACP still has the /* wildcard: python3 tools/harden_acp.py --mns $M"
if [ "$M" -gt 1 ] && [ -f "$D/runs.json" ]; then
  out=$(cd "$D" && python3 server.py --bench 5 --mns "$M" 2>&1 | tail -1)
  p95=$(echo "$out" | sed -n 's/.*p95=\([0-9]*\) ms.*/\1/p')
  [ -n "$p95" ] && { [ "$p95" -le 5000 ] && say OK "read of all cells: $out" || say WARN "read of all cells slow: $out"; } || say WARN "no read timing ($out)"
fi
exit $bad
