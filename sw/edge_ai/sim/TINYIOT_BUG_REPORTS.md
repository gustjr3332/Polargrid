# tinyIoT bug reports (found while building PolaGrid)

Status: **internal draft, not filed.** Project policy: nothing is pushed to any tinyIoT repository; patches live only in
this repository (`sim/patches/`). Each report below is written so it can be pasted into an issue later if the team decides to file.

- Upstream: `seslabSJU/tinyIoT`, found on commit `832205f` (2026-04-07); re-checked on `c140495` (2026-10-06 and 2026-10-07), see the re-check sections
- Configuration: MN-CSE (and one IN-CSE), `DB_SQLITE`, HTTP, MQTT enabled, Ubuntu 24.04 (WSL2), gcc, 8 threads
- Found: 2026-09-29 to 2026-10-06 while running a 12 to 1,000 cell closed-loop control simulation (HTTP, GRP fan-out, subscriptions)
- Severity: **Crash** = process dies, **Data** = wrong/lost data, **Build** = does not compile

| # | Title | Severity | Verified | Patch |
|---|---|---|---|---|
| 1 | `DB_SQLITE` does not compile: missing comma in the `fcnt` table definition | Build | 2026-09-29 | `sqlite-missing-comma.patch` |
| 2 | MN-CSE segfaults when a remote CSE lookup returns 403 | Crash | 2026-09-29 (seen, not root-caused) | none |
| 3 | Resources created through GRP `fopt` never trigger subscription notifications | Data | 2026-10-01 | `fopt-member-notify.patch` |
| 4 | Stack buffer overflow when loading the resource tree from SQLite (`char buf[256]`) | Crash | 2026-10-01 (ASan) | `grp-mid-overflow.patch` |
| 5 | HTTP response larger than 64 KB is truncated but sent with the full `Content-Length` | Data | 2026-10-06 | `large-response.patch` |
| 6 | Concurrent requests crash the CSE (resource tree is not thread safe) | Crash | 2026-10-06 (repro script) | `serialize-requests.patch` (coarse) |

### Re-check against the latest upstream (2026-10-06, partial)

The reports above were written against `832205f` (2026-04-07). Upstream `main` was already **123 commits ahead** (`c140495`, 2026-10-06). We built `c140495` with the same configuration (MN-CSE, SQLite) **without any of our patches** and tested what we could. The check was stopped early, so most rows are open.

| # | Result on `c140495` | Evidence |
|---|---|---|
| 1 | **Fixed upstream** | Builds with `DB_SQLITE` without our patch |
| 2 | Not tested | |
| 3 | **Still present** | `sim/repro/fopt_no_notification.py`: a direct CIN produced a notification, the CIN created through `fopt` produced none |
| 4 | Not tested | Source still has `char buf[256]` at 9 sites (grep only, not proof) |
| 5 | Not tested | `httpd.c` still has `char buf[BUF_SIZE]` in the response function; part of it is commented out, so behavior may have changed |
| 6 | **Undetermined** | The notification-driven repro cannot run while #3 exists (0 of 12 notifications, so no concurrent writes). A variant with notification-independent writers was added to `concurrent_fopt_crash.py` but its comparison run (old build vs latest) was stopped before it produced results, and the variant was not validated on the old build. Upstream history contains `ec1e883 "revert route() lock"` and `669d02b "Fix rt->cb mainlock"`, so locking changed; the effect is unverified |

Consequences: do not file #1 (fixed). Before filing anything, re-run #4, #5 and #6 on the latest commit; our patches were written against the April tree and may not apply to it. Build used: `~/polargrid/latest_build`, run from `~/polargrid/nodes_latest/mn001`.

### Re-check on `c140495`, continued (2026-10-07)

Our development base moved to `c140495` on 2026-10-07 (see `sim/README.md`).

| # | Result on `c140495` | Evidence |
|---|---|---|
| 3 | **Still present**; our patch applies unchanged and fixes it | `fopt_no_notification.py`: with `fopt-member-notify.patch`, the CIN created through `fopt` produces a notification |
| 4 | **Code still present** (not re-run) | `grp-mid-overflow.patch` applies unchanged; `strncpy(buf, sqlite3_column_text(...), bytes)` into `char buf[256]` still at 7 sites |
| 5 | **Fixed upstream** | `http_respond_to_client()` now writes the header from the stack buffer and the body directly from the heap string; our patch no longer applies and is dropped |
| 6 | **Still present** | Build with only `fopt-member-notify.patch`: `concurrent_fopt_crash.py` with N=12 survived 100 rounds, with N=50 the MN died silently (no log line) after about 27,700 CINs. With `serialize-requests.patch` added, N=12 and N=50 both survived 100 rounds |

Not a bug, but a behavior change that broke our IN-routed commands: when the IN forwards a request it rewrites a CSE-relative originator (`CAdmin`) to SP-relative (`/tinyiot/CAdmin`), as TS-0004 requires (the April code did the same). On `c140495` the MN no longer treats `/tinyiot/CAdmin` as the admin, so each `fopt` member returns 4103 while the outer `fopt` response is still 200. Fix on the application side: an ACP on the MN that lists `/tinyiot/CAdmin` (and the cell originators) attached to the target containers and the group.

Plain-words summary: #1 the program cannot be built, #2 to #4 and #6 make it crash, #3 and #5 make it silently do the wrong thing.

---

## 1. `DB_SQLITE` does not compile: missing comma in the `fcnt` table definition

**File:** `sqlite_implement.c` line 196 (table definition array)

**Steps:** set `#define DB_TYPE DB_SQLITE` in `config.h`, run `make`.

**Actual:** compile error. The initializer of the `fcnt` entry ends with `}` and the next entry `{"ts", ...}` follows without a comma.

**Fix:** add the comma (`sim/patches/sqlite-missing-comma.patch`, one character).

---

## 2. MN-CSE segfaults when a remote CSE lookup returns 403

**Steps (as observed):** an MN-CSE that is registered to an IN-CSE retrieves a remote resource and the IN answers 403 (at that time the IN's default ACP was restrictive).

**Actual:** the MN logs `Remote CSE is not online : 403` and then segfaults. A 403 should be reported as an error response, not treated as "CSE offline" followed by a crash.

**Status:** seen once on 2026-09-29, avoided by changing the IN's default ACP (`acor` to `["/*"]`). Root cause not analyzed. Needs a reproduction on a clean setup before filing.

---

## 3. Resources created through GRP `fopt` never trigger subscription notifications

**Steps:**
1. Create AEs, each with a container `command` and a `<sub>` on it (`enc.net = [3]`, notification URI = a local HTTP receiver).
2. Create a `<group>` (`mt=3`) whose `mid` lists the `command` containers.
3. `POST <group>/fopt` with a `<contentInstance>`.

**Expected:** every member container gets a CIN and its subscriber is notified, as if each member had been created by a normal request.

**Actual:** the CINs are created, no notification is sent. The same CIN created by a direct POST does notify.

**Root cause:** `fopt_onem2m_resource()` in `onem2m.c` (the per-member loop around `handle_onem2m_request(memberReq, target_rtnode)`) never calls `notify_via_sub()`, which the normal create path calls.

**Fix:** call `notify_via_sub(memberReq, target_rtnode)` after a successful member operation (`sim/patches/fopt-member-notify.patch`, 2 lines).

**Note:** with `?rcn=0` on the fan-out request no usable notification reached the subscribers in our test (cause not checked). Not reported as a bug, but worth knowing.

---

## 4. Stack buffer overflow when loading the resource tree from SQLite (`char buf[256]`)

**File:** `sqlite_implement.c`, `db_get_all_resource_as_rtnode()` (called at startup by `init_resource_tree()`, `rtManager.c:614`). `char buf[256]` is filled with `strncpy(buf, sqlite3_column_text(...), bytes)` where `bytes` is the real column length, with no upper bound (lines 1019, 1046, 1093). The same pattern exists in 7 places (lines about 394/410, 489/505, 1019/1046/1093, 1235/1272, 1314/1368, 2354/2375).

**Steps:**
1. Create a `<group>` with 100 members (member ids of 25 characters give a `mid` of 2,801 bytes), or one CIN whose `con` is 3,000 bytes.
2. Restart the CSE.

**Actual:** `*** stack smashing detected ***` at startup (the stack protector fires once the overwrite reaches the canary: 83 members crash, 82 survive in a default Ubuntu build). Every TEXT column longer than 255 bytes (`mid`, `acpi`, `nu`, `poa`, `lbl`, `dcse`, CIN `con`) overwrites the stack; the symptom depends on layout. AddressSanitizer reports `stack-buffer-overflow ... WRITE` at those lines. Writing data is fine, so the CSE works until its first restart, which makes this easy to miss.

**Fix:** do not copy into a fixed buffer; point at the row data returned by SQLite (`sim/patches/grp-mid-overflow.patch`, 13 hunks). Verified with ASan, groups of 100 and 300 members, two restarts each, and a 3,000 byte CIN. The PostgreSQL backend does not have this pattern.

---

## 5. HTTP response larger than 64 KB is truncated but sent with the full `Content-Length`

**File:** `httpd.c`, `http_respond_to_client()`: the response (status line, headers, body) is assembled in `char buf[BUF_SIZE]` with `BUF_SIZE = 65535`. The "result size too big" check calls `handle_error()` but the already computed `Content-Length` of the full body is still sent.

**Steps:** `POST <group>/fopt` where the group has 100 members and the CIN `con` is about 700 bytes. The response lists every member's created resource (about 88 KB).

**Actual:** the client sees `Content-Length: 88xxx` but receives 65,021 bytes, e.g. Python `requests`: `IncompleteRead(65021 bytes read, 23704 more expected)`. A fan-out response grows with members times resource size, so this appears at about 150 members for tiny CINs and at 100 members for 700-byte CINs.

**Fix:** allocate the output buffer from the body length (`sim/patches/large-response.patch`). A cleaner alternative is to write headers and body separately.

---

## 6. Concurrent requests crash the CSE (resource tree is not thread safe)

**Symptom:** `SIGSEGV` in a request thread while other requests create resources.

**Backtrace** (SIGSEGV handler via `LD_PRELOAD`, resolved with `addr2line`; the crashing thread):
```
get_object_item          cJSON.c:1900
cJSON_GetObjectItem      cJSON.c:1916
get_ri_rtnode            util.c:2666
rt_search_ri             rtManager.c:530, 536 (recursive)
find_rtnode_by_ri        rtManager.c:505
find_rtnode              rtManager.c:281
fopt_onem2m_resource     onem2m.c:1127
route                    main.c:285
handle_http_request      httpd.c:420
respond / respond_thread httpd.c:235 / 39
```

**Cause (inferred from the backtrace and from the effect of the fix):** each HTTP request runs in its own thread (`respond_thread`). The in-memory resource tree (`rtnode->obj`, a cJSON object) is read by `fopt` while another thread's create operation updates the same parent node, so the reader dereferences freed or half-updated cJSON memory. `main_lock` covers only part of the code paths (for example `find_rtnode_by_ri` takes it, but the writers that modify `rtnode->obj` do not).

**Reproduction:** `sim/repro/concurrent_fopt_crash.py` (needs only `requests`; run where the CSE runs). 12 AEs with subscriptions plus one group; each round sends one `fopt`, and every AE posts a CIN to its own container as soon as its notification arrives.

| build | runs | result |
|---|---|---|
| upstream 832205f + patches 1 to 4 (no serialization) | 6 | **crashed in 3 of 6 runs** (e.g. in round 8 of 100) |
| same + `serialize-requests.patch` | 6 | 0 crashes |

In the PolaGrid closed-loop application (one simulated day per run) the CSE died in 4 of 8 runs without the patch and in 0 of 10 runs with it; it also survived 8 of 8 runs when the client itself sent requests one at a time.

**Fix (coarse):** `serialize-requests.patch` wraps `route(o2pt)` in `httpd.c` with a mutex, so only one request touches the tree at a time.
Cost on the same machine (one measurement each):
- steady write throughput (1,000 AEs, 3,000 CINs, 20 clients): 577 to 295 req/s (`results/bench_tinyiot_mn_serialize_1006.txt`)
- 1,000 cells as 10 MN x 100: fan-out to all cells, p50 349 to 734 ms, p95 382 to 2,996 ms (`results/scale_curve_tinyiot_1006.txt`)

**Side condition of the coarse lock:** the CSE holds the lock while it sends notifications, so a notification receiver must answer 200 before it calls the CSE again, or the two deadlock until a timeout.

**Better fix (not done):** protect reads and writes of `rtnode->obj` (a read-write lock around the resource tree, or copying what the reader needs under the lock) instead of the whole request.

---

## Observations that are not bug reports yet

- **Default SQLite settings are slow for writes.** With the default journal every commit does an fsync: 69 req/s on one MN, CPU 7%. `PRAGMA journal_mode=WAL; synchronous=NORMAL` gives 577 req/s (`sqlite-wal-normal.patch`; safe against application crashes, may lose the last commits on power loss). Worth offering as a config option.
- **Latency grows with accumulated resources.** On an MN database that already held thousands of AEs and subscriptions from earlier runs, the same 1,000-cell fan-out took p95 7.8 s instead of 0.38 s (fresh database). Cause not identified; suspected cost proportional to the number of stored resources.
- **IN-routed `fopt` sometimes returned 404 although the command was delivered** (only on an old database; 200 on a fresh one). Cause not identified.
- **`sdt_definitions` directory is missing in the default build** (`Cannot open SDT directory` warning at startup). Not an error, noted for anyone using SDT data models.
