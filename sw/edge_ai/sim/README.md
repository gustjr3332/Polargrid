# polargrid sim: oneM2M multi-node development environment

## Quick path: Docker

`docker compose up -d` in the repository root builds tinyIoT IN-CSE and MN-CSE (mn001) with `sw/edge_ai/sim/Dockerfile`: a pinned upstream commit (`c140495`) plus the patch in `sw/edge_ai/sim/patches`. The IN listens on port 3000 and the MN on 3001; set `IN_PORT` and `MN_PORT` to publish other host ports. This is all you need for the one-cell and 12-cell runs.

The rest of this file describes the WSL multi-MN setup used for the 1,000-cell runs (one IN and up to ten MNs on one laptop).

A development and simulation setup built on tinyIoT (a oneM2M CSE): one central server (IN-CSE) and N field nodes (MN-CSE), connected over MQTT.

## Layout (WSL Ubuntu 24.04)

| Role | Location | Port | DB | CSE ID |
|---|---|---|---|---|
| IN-CSE | `~/tinyiot_latest/source/server` (until 10-06: `~/tinyIoT`, PostgreSQL) | 3000 | SQLite (`data.db`) | `/tinyiot` |
| MN-CSE (single, manual) | `~/tinyIoT-mn/source/server` | 3001 | PostgreSQL `tinydb_mn` | `/id-mn` |
| MN-CSE ×N (generated) | `~/polargrid/nodes/mnXXX` | 3001 to 3000+N | SQLite (`data.db`) | `/id-mnXXX` |
| MQTT broker | mosquitto | 1883 | n/a | n/a |

The single MN (`~/tinyIoT-mn`) and the generated node mn001 both use port 3001, so do not run them at the same time.

## Usage

**Since 2026-10-07 the base is upstream `c140495`** (`~/tinyiot_latest`, local branch `polagrid` with one commit holding our patches and config; push URL set to `DISABLED`). Patches applied: `fopt-member-notify`, `grp-mid-overflow`, `sqlite-wal-normal`, `serialize-requests`. Bugs #1 (missing comma) and #5 (large response) are fixed upstream, so those patches are dropped. Config: IN also uses SQLite (no permission to create a new PostgreSQL database), `ENABLE_MQTT` on, **`ENABLE_MQTT_WEBSOCKET` off** (on by default in the latest code; without a WebSocket listener in mosquitto the IN exits right after start), QoS 0, `ALLOWED_REMOTE_CSE_ID "/*"`. The IN runs from `~/polargrid/in_nolock` (`tools/run_in.sh`): a copy of `~/tinyiot_latest/source/server` with `serialize-requests.patch` reversed (`patch -R -p3`), as in the April setup where the patches were only in the MN build. With the lock in the IN, forwarded zone commands queue one behind another: 10 zones × 100 cells via IN went from p95 634 ms to 4,741 ms (2026-10-07). Commands routed through the IN also need an ACP on the MN that grants `/tinyiot/CAdmin` (see `TINYIOT_BUG_REPORTS.md`, re-check 2026-10-07; `tools/hier_test.py` creates one per zone); MNs come from `gen_nodes.sh` (build dir `~/polargrid/.build_latest`, `sdt_definitions/` copied per node). The April-based (`832205f`) nodes are kept in `~/polargrid/nodes_832205f`. Start the IN first so MNs can register. Full re-measurement: `bash tools/run_suite_latest.sh <label>`.

```bash
bash tools/run_in.sh                        # 1) IN first (run from sw/edge_ai)
cd ~/polargrid   # copy this repository's sim/ contents to ~/polargrid and work there
./gen_nodes.sh 100                          # 2) build the nodes (about 1 minute, from the config.h in ~/tinyiot_latest)
./nodes.sh start [N]                        # 3) start the nodes
./nodes.sh status                           #    running count / memory
./nodes.sh stop
```

## Check results (2026-09-29, LG gram i7-1195G7 / WSL 7.8 GB)

These are from the April base (`832205f`), before the move to `c140495`.

- 100 of 100 nodes answered over HTTP, and the IN held 100 CSRs
- 101 broker connections; an MQTT request and response succeeded (`/oneM2M/req/Ctest/id-mn050/json` → rsc 2000)
- Total RSS of 100 nodes 541 MB, load average 0.4, no error log lines

## Configuration changes

- `config.h` (IN): `SERVER_TYPE IN_CSE` (the original `IN_CSE or MN-CSE` is a syntax error), `ENABLE_MQTT` on, `MQTT_CLIENT_ID "tinyiot"`, `ALLOWED_REMOTE_CSE_ID "/*"`
- Nodes: `MN_CSE`, `DB_SQLITE` (100 nodes would exceed PostgreSQL's default `max_connections` of 100), `MQTT_CLIENT_ID "id-mnXXX"` (with a duplicate ID the broker drops the earlier connection), `LOG_LEVEL_INFO`
- IN `defaultACP`: `acor ["/id-in","/id-mn"]` → `["/*"]`, changed with a oneM2M PUT. The ACP is stored in the DB when it is first created, so editing the config alone has no effect
- PostgreSQL: moved from 22.04 (PG14) to 24.04 (PG16), restored with `pg_dumpall`, and reset the `tinyuser` password (PG16 uses scram)

## Upstream bugs found (seslabSJU/tinyIoT @ 832205f)

> The full write-up, with reproduction steps, causes, patches and measurements, is `TINYIOT_BUG_REPORTS.md`. The list below is working notes. Reproduction scripts are in `repro/`.
> Partial re-check on 10-06 against the latest upstream (`c140495`, 123 commits ahead): #1 is fixed, #3 is unchanged, the rest were not checked that day. Build `~/polargrid/latest_build`, run `~/polargrid/nodes_latest/mn001`. See `TINYIOT_BUG_REPORTS.md` for the later re-checks.

1. `sqlite_implement.c:196` has no comma after the fcnt schema entry, so a `DB_SQLITE` build fails. Patched only in the `~/polargrid/.build` copy.
2. When an MN gets 403 from a remote CSE lookup, it logs `Remote CSE is not online : 403` and then segfaults.
3. A resource created on a member through GRP `fopt` does not trigger that member's SUB notification (the fan-out loop in `onem2m.c` never calls `notify_via_sub`). Fixed in the `.build` copy only, with `patches/fopt-member-notify.patch`.
4. With a 100-member GRP in the DB, a restart ends in `*** stack smashing detected ***`. Cause: `db_get_all_resource_as_rtnode()` in `sqlite_implement.c` (:1019, :1046, :1093) copies TEXT columns into `char buf[256]` with an unbounded `strncpy`. The same pattern appears in 7 places (:394/410, :489/505, :1019/1046/1093, :1235/1272, :1314/1368, :2354/2375). Any TEXT over 256 bytes (`mid`, `acpi`, `nu`, `poa`, `lbl`, `dcse`, CIN `con`) overwrites memory, and over 2,312 bytes it crashes (with 25-character member ids that is 83 members; 82 pass). A 3,000-byte CIN `con` also crashed on restart. `patches/grp-mid-overflow.patch` (13 hunks, uses the sqlite row pointer instead of copying) fixes it; checked in `~/grp_debug` with ASan, 100 and 300 members, and restarts. Applied to `.build` on 10-01 and all 100 MNs rebuilt. Two restarts with a DB holding a 100-member GRP were clean. The crashing DBs are in `~/polargrid/db_backup/`.
5. When a GRP `fopt` response is larger than 64 KB (`BUF_SIZE` in `httpd.c`), the body is truncated but sent with the full Content-Length. The size is members × member CIN size: a 700-byte command `con` gives about 88 KB at 100 members. `patches/large-response.patch` (10-06, applied to `.build`) makes `http_respond_to_client()` allocate the response on the heap by body length instead of using the stack `buf[BUF_SIZE]`. Do not shrink the response with `?rcn=0`: the fan-out notification body is then empty and no notification goes out.
6. Concurrent requests segfault the MN (10-06). In a closed loop where 12 cells write their angle CIN at the same moment it died about half the time (4 of 8 runs). Backtrace (SIGSEGV handler loaded with `LD_PRELOAD`): `respond_thread` → `route` → `fopt_onem2m_resource` (onem2m.c:1127) → `find_rtnode` → `rt_search_ri` → `get_ri_rtnode` (util.c:2666) → `cJSON_GetObjectItem`. It looks like one thread reads the resource tree (`rtnode->obj`) through fopt while another thread's CIN creation updates the same node, so the first reads a freed object (`main_lock` covers only some paths). Sending the requests one at a time passed 8 of 8. `patches/serialize-requests.patch` wraps the `route()` call in `httpd.c` in a mutex so requests are handled one at a time (applied to `.build`, 10 clean runs in a row). The throughput figures are in `../results/bench_tinyiot_mn_latest_1007.txt`. A notification receiver must return 200 first and call the CSE afterwards: the CSE holds the lock while it sends the notification, so a call made before the reply deadlocks.
7. (MEC033 compatibility, not a bug) `find_rtnode` returns 4004 for CSE-name-less addresses `/<ae-rn>` and `/<ae-rn>/<child>`, which the ETSI Sandbox iot-mgr uses. `patches/find-rtnode-rn-fallback.patch`: when the `ri`/hybrid lookup fails, retry as `<CSE_BASE_NAME>/<addr>` by `rn` (2026-10-10, applied to `~/tinyiot_latest`, checked locally only). Also copy `sdt/mec-iotDev.fcp` into the server `sdt_definitions/` so `mec:iotDev` is accepted.

## Performance patch

- `patches/sqlite-wal-normal.patch` opens SQLite with `journal_mode=WAL` and `synchronous=NORMAL` (set before the first transaction). Steady write throughput went from 69 to 577 req/s (1,000 cells, 3,000 CINs; `../results/bench_tinyiot_mn_wal_1001.txt`). It is safe against an application crash. A power cut can lose the last few commits.
