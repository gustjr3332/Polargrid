#!/usr/bin/env bash
# 계층 측정: IN 확인 → MN M개 재시작 → hier_test.py → results/hier_tinyiot_<MMDD>.txt에 덧붙임
# 사용: bash tools/run_hier.sh "라벨" [M=10] [P=100] [ROUNDS=20] [BG=0] [MODES=edge,in]
cd "$(dirname "$0")/.."
M=${2:-10}; P=${3:-100}; R=${4:-20}; BG=${5:-0}; MODES=${6:-edge,in}
bash tools/run_in.sh >/dev/null
bash ~/polargrid/nodes.sh stop >/dev/null; sleep 1
bash ~/polargrid/nodes.sh start "$M" >/dev/null
for i in $(seq 60); do   # DB가 큰 노드는 시작이 느리다: M개 포트가 모두 열릴 때까지 최대 60초 대기
  [ "$(ss -ltn | grep -cE ":(30(0[1-9]|[1-9][0-9])) ")" -ge "$M" ] && break; sleep 1; done
OUT=results/hier_tinyiot_$(date +%m%d).txt
{ echo "# $1  MN=$M x $P panels rounds=$R bg=${BG}/s modes=$MODES  $(date '+%F %T')"
  echo "  $(bash ~/polargrid/nodes.sh status)"
  timeout 1500 python3 tools/hier_test.py --mns "$M" --per "$P" --rounds "$R" --bg "$BG" --modes "$MODES" 2>&1
  echo "  after: $(bash ~/polargrid/nodes.sh status)"; } | tee -a "$OUT"
