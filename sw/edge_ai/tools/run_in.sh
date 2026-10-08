#!/usr/bin/env bash
# IN-CSE(~/polargrid/in_nolock = ~/tinyiot_latest 사본에서 직렬화 패치만 되돌린 빌드, 포트 3000, SQLite)를 띄운다. IN에 직렬화 락이 있으면 구역 fopt 전달이 한 줄로 서서 10구역 p95가 4.7초까지 늘었다(10-07). MN은 시작할 때 IN에 등록하므로 IN이 먼저 떠 있어야 한다.
if ss -ltn "sport = :3000" | grep -q LISTEN; then echo "IN already running"; exit 0; fi
sudo -n service postgresql start >/dev/null 2>&1 || true
sudo -n service mosquitto start >/dev/null 2>&1 || true
cd ~/polargrid/in_nolock && setsid nohup ./server > /tmp/in.log 2>&1 < /dev/null &
sleep 3
ss -ltnp "sport = :3000" | tail -1
