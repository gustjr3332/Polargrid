#!/usr/bin/env bash
# fanout_test.py 실행 결과를 results/fanout_tinyiot_<MMDD>.txt에 덧붙인다. 사용: bash tools/run_fanout.sh "라벨" [N=100] [ROUNDS=20]
cd "$(dirname "$0")/.."
OUT=results/fanout_tinyiot_$(date +%m%d).txt
echo "# $1  N=${2:-100} rounds=${3:-20}  $(date '+%F %T')" | tee -a "$OUT"
timeout 900 python3 tools/fanout_test.py --n "${2:-100}" --rounds "${3:-20}" 2>&1 | tee -a "$OUT"
