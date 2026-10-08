#!/usr/bin/env bash
# MN 1~N개를 새 DB로 다시 띄운다(기존 DB는 ~/polargrid/db_backup/<시각>/ 으로 이동). 자원이 쌓인 DB는 느려지므로(개발.md 0-4d) 측정 전에 쓴다.
# 사용: bash tools/fresh_mn.sh [N=1]   (IN은 먼저 떠 있어야 함: tools/run_in.sh)
N=${1:-1}; TS=$(date +%H%M%S)
bash ~/polargrid/nodes.sh stop >/dev/null; sleep 1
mkdir -p ~/polargrid/db_backup/$TS
for d in ~/polargrid/nodes/mn*; do
  [ -f "$d/data.db" ] && mv "$d/data.db" ~/polargrid/db_backup/$TS/$(basename "$d").db
  rm -f "$d/data.db-wal" "$d/data.db-shm"
done
bash ~/polargrid/nodes.sh start "$N"; sleep 3
