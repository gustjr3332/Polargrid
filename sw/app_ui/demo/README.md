# Demo page server

**One-command start (2026-10-19, WSL, from `sw/app_ui/demo/`):** `bash demo_up.sh real | virtual [M] | replay`, stop with `bash demo_down.sh`, check with `bash preflight.sh [M]`.
`real` starts the IN, one fresh MN, narrows its defaultACP, `tools/real_cell.py app` and the server for the phone app (then start the cell, or `tools/fake_cell.py --run real1`).
`virtual` starts M fresh MNs (default 10), narrows their defaultACP, the zones (waiting for Start on the page) and the server. Every start uses a fresh MN database (the old one goes to
`~/polargrid/db_backup/`), because a database full of old resources was slow (docs 0-8 #9). **Simulation pace (2026-10-19):** one step is 10 simulated minutes (`run_zones.sh` default, `--step 10`). At 1x one step is meant to take 1 s (10 minutes per second), 2x 0.5 s, 5x 0.2 s; the 10x option is gone and the zones refuse any other speed. **Live, with 1,000 cells, this pace is not reached:** measured on this laptop, steps ran at only about 6 simulated minutes per second at 1x, 2x and 5x alike (one step takes about 1.6 s because each command goes through the CSE), and reading all cells took 2.5 s at the start and 9 to 15 s later in the day, so the page updates every several seconds. **The recording does keep the pace:** `bash record_day.sh` (25 to 30 minutes, run once) records a day at speed 0.05 and `make_replay10.py` turns it into `replay/day_10min.jsonl`, exactly 72 frames from 07:00 to 18:50 (no mark missing). `demo_up.sh replay` plays it, one frame per second at 1x; the speed select (1x, 2x, 5x) is the only control in replay. Measured: 1x 10.0, 2x 20.0, 5x 47.5 simulated minutes per second (a 5x run over the end of the day reads lower). The recording is git-ignored, copy it to the stage laptop by hand.

**Access token:** `demo_up.sh` makes a random token for every start and passes it to `server.py --token` (or env `DEMO_TOKEN`). With a token set, every POST (move cells, save a correction, Start/Stop of the zones) must send it as `X-Demo-Token`, otherwise the server answers 401; reads stay open. The printed links already contain `?token=...`; the page keeps it in localStorage, so open the link once on each device. A page opened without it shows "No access token". The token only stops other people on the same Wi-Fi from moving the cells, it is sent in plain http and is not a login. Checked: no token and a wrong token give 401, the right one 200, and a headless Chrome moved the cell 30 to 70 with the token and stayed at 30 without it. Without `--token` the server prints a note and accepts every POST. `preflight.sh` reports whether a POST without the token is refused. Orphaned `mosquitto_sub` processes of earlier servers piled up; `demo_down.sh` now kills them. Piping `demo_up.sh` into another command (`| grep`) waits for the server, so run it directly in the terminal.

`real` and `virtual` both use MN 1, so run one at a time. Checked on this laptop: `virtual`
was up in 18 s, `preflight.sh 10` all OK, a read of all 1,000 cells on the fresh databases took p50 1.1 to 1.2 s and p95 1.2 s (idle, 5 and 7 reads; under a running day the command latency is still
p95 4.4 to 6.7 s, see below). `preflight.sh` fails if the IN or an MN is down, the demo server is missing or a defaultACP still has the wildcard, and warns about a database over 100 MB (a guess, not a measured limit) or a slow read.


Viewer-role (read-only) FastAPI server for the 1,000-cell demo page and the flow viewer. Run it inside WSL, next to the CSEs.

```bash
pip install --user --break-system-packages fastapi uvicorn   # WSL has no pip: python3 get-pip.py --user --break-system-packages first
cd sw/app_ui/demo
python3 server.py --live --mns 10                 # http://localhost:8000/ (demo page), /flow (flow viewer)
python3 server.py --live --mns 10 --record replay/day.jsonl
python3 server.py --replay replay/day.jsonl --loop
python3 server.py --bench 7 --mns 10              # time 7 full reads of all cells, then exit
```

- `runs.json` maps MN number to the run id of its cells (`{"1": "r34365", ...}`). Write it from the `[setup] ... run rNNNNN` lines of
  `python3 -m polagrid.closed_loop`. The server never probes with an unknown originator: that crashed an MN with 100 cells.
- Endpoints: `/api/frame` (`?fresh=1` reads now), `/api/events` (SSE frames), `/api/topology`, `/api/flow` (SSE events for `/flow`).
- The frame has `glare_h` and `lat_ms` as `null`: a viewer cannot see them. `desks` is `[mean lux, min lux]` over all desks.
- `/flow` shows the resource tree and the event stream. It polls the newest CIN of each zone's sun, desks and cell 0 command every
  second, cell states every frame, and relays `mosquitto_sub -t '#'` (IN-MN MQTT). Its polling adds load to the MNs.

- Replay starts the recorded day when the first page connects, plays once, then stays on the last frame (`--loop` repeats it).
- Comparison table: `python3 make_compare.py` builds `compare.json` from `sw/edge_ai/results/baseline_compare.csv`; the page shows it
  with the "Comparison table" button. Rehearsal steps and the fallback: `REHEARSAL.md`.
