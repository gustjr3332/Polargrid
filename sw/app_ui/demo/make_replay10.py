"""Turn a slow recording (frames at irregular times) into a day of exact 10-minute frames: replay/day_10min.jsonl.

For every mark 07:00, 07:10 ... 18:50 it takes the first recorded frame whose simulated time is in [mark, mark + 10 min).
A mark with no such frame repeats the frame before it (counted and printed). The page plays one frame per second at 1x,
so 1 s = 10 simulated minutes, 2x and 5x give 0.5 s and 0.2 s.

    python3 make_replay10.py replay/rec_slow.jsonl replay/day_10min.jsonl
"""
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
frames = [json.loads(line) for line in open(src) if line.strip()]
minute = lambda f: int(f["t"][11:13]) * 60 + int(f["t"][14:16])
out, held, prev = [], 0, frames[0]
for mark in range(7 * 60, 18 * 60 + 51, 10):
    hit = next((f for f in frames if mark <= minute(f) < mark + 10), None)
    if hit is None:
        held += 1
        hit = prev
    out.append(hit)
    prev = hit
with open(dst, "w") as fh:
    fh.writelines(json.dumps(f) + "\n" for f in out)
print(f"{len(out)} frames written to {dst}; {held} marks had no recorded frame and repeat the one before")
