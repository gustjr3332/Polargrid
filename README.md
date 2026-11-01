# PolaGrid

PolaGrid cuts glare at the desk without darkening the room. A window is divided into cells, each cell holds a rotating polarizing film, and an AI turns only the cells whose light lands on a desk. The cells are oneM2M devices: one cell is one AE, and the controller talks to them through a standard CSE.

This repository is open source (MIT). It holds the edge AI, the ESP32 firmware for one real cell, the demo and phone-app mockup, and the hardware notes. It was built by one person for a university maker contest, and it is being prepared for the oneM2M developer contest.

## The problem

With the sun on a monitor or a book, most people pull the blind down, and then the room is dark enough that the lights go on. The sun also moves, so the blind goes up and down all day, and the seat next to you gets different light from the same window. Glare is about where the light lands, not how much of it there is.

Motorized blinds and electrochromic glass still act on the whole window or a whole pane. Reservation timers and room-wide brightness sensors cannot see that one desk is glared and the next is not.

## How it works

One cell is a fixed polarizing film on the inside of the glass plus a disc with a second film that a stepper motor turns from 0 to 90 degrees. At 0 the cell is open, at 90 it is closed, and the angle in between sets how much light passes. A cell never blocks the whole view: even fully open it passes at most about half the light of bare glass (a design assumption, not a measurement).

Each cell has a light sensor, and each desk has one. The cell is built from an ESP32, a 28BYJ-48 stepper, a timing belt and pulley, and two BH1750 sensors. Cells are sold one at a time, and a central control module ties them together.

```
desk sensor -> ESP32 (Bluetooth or Wi-Fi) -> MN-CSE (oneM2M) -> AI loop -> command -> disc turns
```

The CSE is tinyIoT in an IN plus MN hierarchy. A room's cells form one group, so one command per zone reaches every cell. If the link drops, a cell opens by itself after 60 seconds, there is no camera anywhere, and at night the cells close.

The AI has three stages:

1. Contribution estimation. After installation the system works out how much each cell lights each desk, with no setup of window size or desk position.
2. Angle decision. It sets each cell's angle so no desk goes over the glare limit. It reads sensor values only.
3. Per-room learning. It predicts the next day from each room's own data, and a phone app lets users correct comfort settings. A pre-trained preference model for the real cell starts from 36 virtual-user samples and keeps learning from app corrections.

## Results

Everything in this section except the real-cell rows is simulation. Say so wherever you quote it.

Glare, in desk-hours per day (lower is better), 12-cell virtual room, 20-day mean, two desks summed:

| Controller | Glare | Note |
|---|---|---|
| Fixed open | 2.26 | |
| Timed schedule | 0.34 | |
| AI stages 1 and 2 | 0.06 | 0.44 desk-hours darker at the desk than fixed open |
| Blind | 0.00 | desk is dark longest, 21.2 h |

Stage 3: a model trained on another room has 3.04 to 4.12 h of glare. Retrained on 30 days of the room's own data it has 0.05 to 0.23 h.

Scale and resilience on one laptop (WSL, 8 threads), 1,000 virtual cells in 10 zones, one measurement series each:

- Command to angle p95 is 1.8 to 2.9 s when the zones run five at a time. Run all ten at once on this machine it is 4.4 to 6.7 s, which misses the 5 s target in two of four runs.
- Taking the IN down for 240 s left all 48 zone-control requests successful. Requests routed through the IN failed.

Real cell, one unit stuck to a window, daytime, 1 November:

- After the closed angle was tuned from two sweeps, a closed cell reads 0.0 lux at the cell sensor, against 113 to 132 lux open. The desk sensor falls from about 62 to 72 lux to 1.7 lux, roughly 2.7%.
- Readings drift with the sky. In a repeat sweep the same 0 degree point read 5% apart in one run and 42% apart in another, so treat these as one-day numbers from one cell.
- The film's true open position sits outside the motor's range, so "open" is only partly open.

There is no saving figure for electricity here, because none was measured. The 20.6% (cooling) and 19.5% (lighting) share of Korean large-building electricity (2016, apartments excluded) is background, not something PolaGrid achieves.

## Run it

You need a Linux shell (the project is developed on WSL Ubuntu), Python 3, and a tinyIoT build. The tinyIoT patches, configs and node scripts are in `sw/edge_ai/sim`, and `sw/edge_ai/sim/README.md` explains how to build it.

Virtual 1,000-cell demo and the phone-app mockup:

```bash
cd sw/app_ui/demo
bash demo_up.sh virtual 10     # 10 zones of 100 cells, page at http://localhost:8000
bash preflight.sh 10           # checks the stack
bash demo_down.sh              # stops it
```

`demo_up.sh replay` plays a recorded day instead of running the zones live, which is faster than real time. The page follows Start, Stop, speed and cloud controls.

One real cell:

```bash
cd sw/app_ui/demo && bash demo_up.sh real                 # IN plus one MN
cd sw/edge_ai
python tools/bt_bridge.py --port COM4 --run real1          # Windows, paired Bluetooth COM port
python3 tools/real_cell.py --run real1 ai --close-lux 150  # AI loop, simulated sun, real desk sensor
```

The firmware is in `sw/actuator`. Copy `src/secrets.example.h` to `src/secrets.h`, then `pio run -e bt -t upload` flashes the Bluetooth build over USB (there is no over-the-air update in that build). `env:esp32dev` is the Wi-Fi build and has not been re-tested since the Bluetooth work.

Tests:

```bash
cd sw/edge_ai && python -m pytest tests -q
cd ../actuator && g++ -std=c++17 -I src tests_host/test_logic.cpp -o test_logic && ./test_logic
```

## Layout

- `hw/`: hardware notes, wiring diagrams, parts
- `sw/edge_ai/`: the `polagrid` package (physics model, AI stages, oneM2M client), tests, tools, simulator setup, results
- `sw/actuator/`: ESP32 firmware, with host-side tests
- `sw/app_ui/`: phone-app mockup and the demo server

## Status and limits

This is a prototype. What is not done:

- A `docker compose up` quick start with a first CIN inside five minutes is a goal, not something this repository provides yet.
- The 1,000 cells are virtual. Only one real cell exists.
- The real cell's AI loop closes by a desk-lux threshold. The rule reads a falling desk value as a reason to reopen, so with a continuous flashlight the cell can open and close in a loop. A minimum hold time after closing would fix it, and it is not written yet.
- The ACP hardening, TLS, SAREF mapping and MEC VM deployment planned for the contest are not in this repository.

## Contributing

Issues and pull requests are welcome. For code changes, run the tests above first. Do not commit secrets, `secrets.h`, MEC Sandbox session URLs or database files.

## License

MIT, see `LICENSE`.
