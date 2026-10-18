# edge_ai

PolaGrid edge AI: the `polagrid` package (physics model, AI (1) to (3), oneM2M client, zone controller), tests,
tools and results. Run commands from this folder. The tinyIoT setup is described in `sim/README.md`.

## Real cell (one control module)

`tools/real_cell.py` drives the one real cell running the ESP32 firmware in `sw/actuator`. It uses the same MN-CSE,
run id and originators as the firmware, and runs the polagrid `Controller` for a one-cell zone. Run it inside WSL
next to the MN, because the CSE sends desk notifications back to this process (port 9791 by default).

`--run`, `--cse` and `--host` must match `RUN_ID`, `CSE_NAME` and `CSE_HOST` in `sw/actuator/src/secrets.h`. The
host is the MN as this PC sees it, usually `http://127.0.0.1:3001`. Defaults are `real1`, `TinyIoT-mn001` and
`http://127.0.0.1:3001`.

```bash
bash tools/run_in.sh && bash ~/polargrid/nodes.sh start 1     # IN, then mn001 on port 3001
python3 tools/real_cell.py --run real1 manual                 # type angles 0..90 (0 = open), q to quit
python3 tools/real_cell.py --run real1 manual 45 90 0         # same, angles from the command line
python3 tools/real_cell.py --run real1 sweep --n 5            # 0,10,..,90,0 deg -> results/real_cell_sweep_*.csv
python3 tools/real_cell.py --run real1 ai --speed 120         # AI (1)+(2), sun from a SIMULATED clock
```

- `manual` prints, for each angle, the time from command to the cell's desk reply (the disc needs about 13 s for
  90 deg; the controller waits up to 30 s), the `state` opeLl next to the expected value, the desk lux and the newest
  cell-sensor reading (posted every 10 s, so it can be up to 10 s old).
- `sweep` waits for the cell's reply at each angle, averages `--n` new readings of `--sensor cell` (default) or
  `desk`, writes `angle, lux, ratio` (ratio to the first 0 deg point) and prints the fit
  `lux = a cos^2(angle - offset) + b` with its rms residual. The offset is the 0 deg calibration error.
- `ai` runs `online.polagrid_online` on a one-cell, one-desk room. Desk lux comes from the real sensor. The sun
  position and outdoor light come from a simulated clock (`--start`, `--speed`, `--cloud`) because the demo lights
  the cell with an LED lamp. The AI closes the cell only when the desk reads more than about 1,000 lux, and it opens
  fully whenever the simulated outdoor light is below 20,000 lux.
- In every mode the last angle is resent at least every 10 min of wall time, before the cell's 30 min watchdog.
  On exit or Ctrl+C the script sends OPEN (0 deg). If the CSE is unreachable it retries with backoff 1, 2, 4 ... 60 s
  and does not exit. Setup is safe to repeat with the same run id, and command ids start from the Unix time so a
  restarted script never repeats an id the cell has already applied.

Without hardware, start `python3 tools/fake_cell.py --run <id>` first. It follows the firmware's resources and
timing over HTTP and reports a made-up cos^2 light model. Its readings carry `"fake": true`, and `sweep` then names
the CSV `real_cell_sweep_FAKE_*.csv` with a FAKE header line. Use a run id other than the real one (for example
`fk1`) so fake readings never sit in the real cell's containers.

Tests for the pure parts (backoff, retry, averaging, fit): `python -m pytest -q tests/test_real_cell.py`.
