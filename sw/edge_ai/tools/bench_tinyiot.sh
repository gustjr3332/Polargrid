#!/usr/bin/env bash
# tinyIoT CSE 1개에 칸 N개 설치 + 운영 CIN W건 측정 (bench_acme.sh와 같은 조건), 구조 2종(ae/zone) 비교.
# WSL에서 실행: bash tools/bench_tinyiot.sh [N=1000] [W=3000] [BASE=http://127.0.0.1:3001/TinyIoT-mn001]
# 대상 CSE가 미리 떠 있어야 한다(sim/README.md). 측정 중 CSE 프로세스 CPU 최대치를 1초 간격으로 기록.
N=${1:-1000}; W=${2:-3000}; BASE=${3:-http://127.0.0.1:3001/TinyIoT-mn001}
PORT=$(echo "$BASE" | sed -E 's|.*:([0-9]+)/.*|\1|')
PID=$(ss -ltnp "sport = :$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)
export COLUMNS=200 LINES=50   # WSL 비대화형 셸에서 ps 경고 방지
cd "$(dirname "$0")/.."
echo "# tinyIoT bench $(date '+%F %T')  N=$N W=$W BASE=$BASE pid=$PID"
for layout in ae zone; do
  echo "== layout=$layout"
  ( peak=0; while kill -0 "$PID" 2>/dev/null; do
      c=$(ps -o %cpu= -p "$PID" | tr -d ' '); c=${c%.*}; [ "${c:-0}" -gt "$peak" ] && peak=$c
      echo "$peak" > /tmp/bench_cpu_peak; sleep 1; done ) &
  mon=$!
  python3 tools/scale_smoke.py --n "$N" --workers 20 --layout "$layout" --writes "$W" --base "$BASE"
  kill $mon 2>/dev/null
  echo "  cse_cpu_peak=$(cat /tmp/bench_cpu_peak)%  rss=$(( $(awk '/VmRSS/{print $2}' /proc/$PID/status) / 1024 ))MB"
done
