#!/usr/bin/env bash
# 진단용: mn001을 tmpfs(/dev/shm)에서 새 DB로 띄워 디스크 I/O(SQLite 커밋) 영향을 분리한다.
set -e
kill $(ss -ltnp "sport = :3001" | grep -oP 'pid=\K[0-9]+') 2>/dev/null || true
sleep 1
rm -rf /dev/shm/mn001 && mkdir -p /dev/shm/mn001
cp ~/polargrid/nodes/mn001/server /dev/shm/mn001/
cd /dev/shm/mn001 && setsid nohup ./server > server.log 2>&1 < /dev/null &
sleep 3
ss -ltnp "sport = :3001" | tail -1
