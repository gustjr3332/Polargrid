#!/bin/sh
# ACME 설정 × 저장 구조 비교. 매 실행마다 새 컨테이너(빈 DB)로 시작.
# 사용: sh tools/bench_acme.sh [N] [WRITES]   (Git Bash, polargrid/sw/edge_ai 폴더에서)
N=${1:-1000}; W=${2:-3000}
cd "$(dirname "$0")/.."
mkdir -p results
for cfg in default logoff memory; do
  for layout in ae zone; do
    docker rm -f acme-bench >/dev/null 2>&1
    MSYS_NO_PATHCONV=1 docker run -d --name acme-bench -p 8080:8080 \
      -v "$(pwd -W 2>/dev/null || pwd)/tools/acme_configs/$cfg.ini:/data/acme.ini" \
      ankraft/acme-onem2m-cse >/dev/null
    until curl -s -m 2 -o /dev/null -H 'X-M2M-Origin: CAdmin' -H 'X-M2M-RI: 1' -H 'X-M2M-RVI: 3' localhost:8080/cse-in; do sleep 1; done
    echo "=== cfg=$cfg layout=$layout ==="
    python tools/scale_smoke.py --n "$N" --workers 20 --layout "$layout" --writes "$W"
    docker stats acme-bench --no-stream --format 'mem={{.MemUsage}}'
  done
done | tee "results/bench_acme_$(date +%m%d_%H%M).txt"
docker rm -f acme-bench >/dev/null
