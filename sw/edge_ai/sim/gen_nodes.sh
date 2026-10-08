#!/usr/bin/env bash
# MN-CSE 노드 N개 생성: ~/polargrid/nodes/mnXXX/server (SQLite, MQTT 사용)
# 사용법: ./gen_nodes.sh [N=100] [BASE_PORT=3001]
set -e
N=${1:-100}; BASE=${2:-3001}
SRC=${SRC:-~/tinyiot_latest/source/server}   # upstream c140495 + 로컬 패치 커밋(브랜치 polagrid)
BUILD=${BUILD:-~/polargrid/.build_latest}
OUT=~/polargrid/nodes
mkdir -p "$OUT"
if [ ! -d "$BUILD" ]; then cp -r "$SRC" "$BUILD"; fi
cp "$SRC/config.h" "$BUILD/config.h.base"
cd "$BUILD"
for i in $(seq 1 "$N"); do
  id=$(printf "mn%03d" "$i"); port=$((BASE + i - 1))
  sed -e 's/^#define SERVER_TYPE .*/#define SERVER_TYPE MN_CSE/' \
      -e "s/^#define SERVER_PORT .*/#define SERVER_PORT \"$port\"/" \
      -e "s/^#define CSE_BASE_NAME .*/#define CSE_BASE_NAME \"TinyIoT-$id\"/" \
      -e "s/^#define CSE_BASE_RI .*/#define CSE_BASE_RI \"id-$id\"/" \
      -e 's|^#define REMOTE_CSE_ID .*|#define REMOTE_CSE_ID "/tinyiot"|' \
      -e 's/^#define REMOTE_CSE_NAME .*/#define REMOTE_CSE_NAME "TinyIoT"/' \
      -e 's/^#define REMOTE_CSE_HOST .*/#define REMOTE_CSE_HOST "127.0.0.1"/' \
      -e 's/^#define REMOTE_CSE_SP_ID .*/#define REMOTE_CSE_SP_ID "tinyiot.example.com"/' \
      -e 's/^#define REMOTE_CSE_PORT .*/#define REMOTE_CSE_PORT 3000/' \
      -e 's/^#define DB_TYPE DB_POSTGRESQL/#define DB_TYPE DB_SQLITE/' \
      -e "s/^#define MQTT_CLIENT_ID .*/#define MQTT_CLIENT_ID \"id-$id\"/" \
      -e 's/^#define LOG_LEVEL LOG_LEVEL_DEBUG/#define LOG_LEVEL LOG_LEVEL_INFO/' \
      config.h.base > config.h
  # Makefile이 config.h 의존성을 모르므로, config.h를 쓰는 오브젝트만 지움(sqlite/libcoap은 재사용)
  rm -f *.o resources/*.o websocket/*.o wolfmqtt/*.o server
  make -s -j8 >/dev/null 2>build.err || { echo "build fail $id"; tail -5 build.err; exit 1; }
  mkdir -p "$OUT/$id"; cp server "$OUT/$id/server"; cp -r sdt_definitions "$OUT/$id/" 2>/dev/null || true
  echo "$id port $port"
done
