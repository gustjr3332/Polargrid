# tinyIoT IN-CSE and MN-CSE (mn001, port 3001) from upstream commit c140495 plus the PolaGrid patch.
# Build context: sw/edge_ai/sim.  Upstream is BSD-3-Clause (tinyIoT Contributors).
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
ARG TINYIOT_SHA=c140495622a6271fe16c8cf92315c2892c803003
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config libssl-dev libwebsockets-dev git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY patches/polagrid-c140495.patch /tmp/polagrid.patch
RUN git init -q /src && cd /src \
    && git remote add origin https://github.com/seslabSJU/tinyIoT.git \
    && { git fetch -q --depth 1 origin "$TINYIOT_SHA" || git fetch -q origin; } \
    && git checkout -q "$TINYIOT_SHA" \
    && git apply /tmp/polagrid.patch

WORKDIR /src/source/server
# IN: patched config.h as is.  sdt_init("./sdt_definitions") reads from the run directory.
RUN make -s -j4 \
    && mkdir -p /opt/tinyiot/in && cp server /opt/tinyiot/in/ && cp -r sdt_definitions /opt/tinyiot/in/

# MN: same sed as sim/gen_nodes.sh for mn001 / port 3001. Only the objects that include config.h are rebuilt.
RUN cp config.h config.h.base \
    && sed -e 's/^#define SERVER_TYPE .*/#define SERVER_TYPE MN_CSE/' \
      -e 's/^#define SERVER_PORT .*/#define SERVER_PORT "3001"/' \
      -e 's/^#define CSE_BASE_NAME .*/#define CSE_BASE_NAME "TinyIoT-mn001"/' \
      -e 's/^#define CSE_BASE_RI .*/#define CSE_BASE_RI "id-mn001"/' \
      -e 's|^#define REMOTE_CSE_ID .*|#define REMOTE_CSE_ID "/tinyiot"|' \
      -e 's/^#define REMOTE_CSE_NAME .*/#define REMOTE_CSE_NAME "TinyIoT"/' \
      -e 's/^#define REMOTE_CSE_HOST .*/#define REMOTE_CSE_HOST "127.0.0.1"/' \
      -e 's/^#define REMOTE_CSE_SP_ID .*/#define REMOTE_CSE_SP_ID "tinyiot.example.com"/' \
      -e 's/^#define REMOTE_CSE_PORT .*/#define REMOTE_CSE_PORT 3000/' \
      -e 's/^#define DB_TYPE DB_POSTGRESQL/#define DB_TYPE DB_SQLITE/' \
      -e 's/^#define MQTT_CLIENT_ID .*/#define MQTT_CLIENT_ID "id-mn001"/' \
      -e 's/^#define LOG_LEVEL LOG_LEVEL_DEBUG/#define LOG_LEVEL LOG_LEVEL_INFO/' \
      config.h.base > config.h \
    && rm -f *.o resources/*.o websocket/*.o wolfmqtt/*.o server \
    && make -s -j4 \
    && mkdir -p /opt/tinyiot/mn && cp server /opt/tinyiot/mn/ && cp -r sdt_definitions /opt/tinyiot/mn/
