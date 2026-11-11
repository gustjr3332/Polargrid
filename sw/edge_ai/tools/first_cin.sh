#!/usr/bin/env bash
# Time from `docker compose up` to the first CIN on mn001. Run from the repository root: bash sw/edge_ai/tools/first_cin.sh
# COLD=1 also rebuilds the images without cache and counts that time. Gives up after 300 s.
set -o pipefail   # the FAIL exit 1 below runs inside a pipe to tee
cd "$(dirname "$0")/../../.." || exit 1
OUT=sw/edge_ai/results/first_cin_$(date +%m%d).txt
H=(-H 'X-M2M-Origin: CAdmin' -H 'X-M2M-RI: fc' -H 'X-M2M-RVI: 3')
{
  t0=$(date +%s)
  [ "${COLD:-0}" = 1 ] && docker compose build --no-cache
  docker compose up -d
  while :; do
    n=$(docker compose exec -T mn curl -sf "${H[@]}" 'http://127.0.0.1:3001/TinyIoT-mn001?fu=1&ty=4&lim=1' 2>/dev/null | grep -o '"m2m:uril":\[[^]]' | wc -l)
    [ "$n" -gt 0 ] && break
    if [ $(( $(date +%s) - t0 )) -gt 300 ]; then
      echo "FAIL: no CIN within 300 s"; docker compose logs --tail 30; exit 1
    fi
    sleep 1
  done
  echo "first CIN after $(( $(date +%s) - t0 )) s (cold=${COLD:-0})"
  echo "mn001 registered on IN:"; docker compose exec -T in curl -s "${H[@]}" 'http://127.0.0.1:3000/TinyIoT?fu=1&ty=16'
  echo
} 2>&1 | tee "$OUT"
