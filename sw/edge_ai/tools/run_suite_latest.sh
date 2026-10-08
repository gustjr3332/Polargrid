#!/usr/bin/env bash
# tinyIoT 기반을 바꾼 뒤 전체 재측정: 버그 재현(3·6번) → MN 처리량 → 구역 명령 전달 → 1,000칸 계층 곡선 → 폐루프.
# 매 단계 새 DB. 사용(WSL): bash tools/run_suite_latest.sh "라벨"   결과는 results/*_<MMDD>.txt
cd "$(dirname "$0")/.."
L=${1:-latest}; D=$(date +%m%d)
fresh() { bash tools/fresh_mn.sh "${1:-1}" >/dev/null; }
step() { echo; echo "######## $1  $(date '+%F %T')"; }

bash tools/run_in.sh
step "repro #3 (fopt member notify)"; fresh
timeout 120 python3 sim/repro/fopt_no_notification.py 2>&1 | tail -3
for n in 12 50; do
  step "repro #6 concurrent N=$n x100"; fresh
  timeout 1200 python3 sim/repro/concurrent_fopt_crash.py http://127.0.0.1:3001/TinyIoT-mn001 $n 100 2>&1 | tail -2
done

step "bench MN throughput"; fresh
bash tools/bench_tinyiot.sh 1000 3000 | tee results/bench_tinyiot_mn_${L}_$D.txt

step "fanout 100"; fresh
bash tools/run_fanout.sh "$L (fresh DB)" 100 20 | tail -4

step "scale curve"
bash tools/run_scale_curve.sh "$L" "1 2 5 10" 100 10

OUT=results/closed_loop_$D.txt
echo "# 폐루프 $L $(date '+%F %T')" >> $OUT
for args in "--controller probe" "--controller predict" "--rows 10 --cols 10 --controller predict --train-days 30"; do
  step "closed loop $args"; fresh
  echo "== $args" >> $OUT
  timeout 1800 python3 -m polagrid.closed_loop $args 2>&1 | tee -a $OUT | tail -6
done
step "suite done"
