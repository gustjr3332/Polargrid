#!/usr/bin/env bash
# mn001을 디스크(~/polargrid/nodes/mn001, SQLite on ext4)에서 다시 띄운다. tmpfs 진단 후 원상복구용.
kill $(ss -ltnp "sport = :3001" | grep -oP 'pid=\K[0-9]+') 2>/dev/null || true
sleep 1
cd ~/polargrid/nodes/mn001 && setsid nohup ./server > server.log 2>&1 < /dev/null &
sleep 3
for p in $(ss -ltnp "sport = :3001" | grep -oP 'pid=\K[0-9]+'); do echo "3001 pid=$p cwd=$(readlink /proc/$p/cwd)"; done
