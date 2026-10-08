#!/usr/bin/env bash
# 구역 수(MN 수)에 따른 명령 전달 지연 곡선. 매 단계 MN DB를 새로 시작(기존 DB는 ~/polargrid/db_backup/로 이동)하고
# 측정 중 시스템 CPU 사용률(vmstat)을 같이 기록한다. 사용: bash tools/run_scale_curve.sh "라벨" "1 2 5 10" [P=100] [ROUNDS=10] [BG=0]
cd "$(dirname "$0")/.."
LABEL=$1; STEPS=${2:-"1 2 5 10"}; P=${3:-100}; R=${4:-10}; BG=${5:-0}
OUT=results/scale_curve_tinyiot_$(date +%m%d).txt
TS=$(date +%H%M%S)
for M in $STEPS; do
  bash ~/polargrid/nodes.sh stop >/dev/null; sleep 1
  mkdir -p ~/polargrid/db_backup/$TS
  for d in ~/polargrid/nodes/mn*; do
    [ -f "$d/data.db" ] && mv "$d/data.db" ~/polargrid/db_backup/$TS/$(basename "$d").db
    rm -f "$d/data.db-wal" "$d/data.db-shm"
  done
  vmstat 1 > /tmp/vmstat_$M.log & VM=$!
  bash tools/run_hier.sh "$LABEL (fresh DB)" "$M" "$P" "$R" "$BG" edge,in | grep -E "^\[|^#" | tee -a "$OUT"
  kill $VM
  awk 'NR>2 {n++; us+=$13; sy+=$14; wa+=$16; if (100-$15>mx) mx=100-$15} END {printf "  cpu avg us=%.0f%% sy=%.0f%% wa=%.0f%% busy-max=%d%%\n", us/n, sy/n, wa/n, mx}' /tmp/vmstat_$M.log | tee -a "$OUT"
done
