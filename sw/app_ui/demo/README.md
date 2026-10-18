# Demo page server

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
