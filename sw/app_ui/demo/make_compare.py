#!/usr/bin/env python3
"""Build compare.json (the demo page's comparison table) from the measured baseline CSV.

    python3 make_compare.py        # reads sw/edge_ai/results/baseline_compare.csv, writes compare.json here

The CSV comes from `python -m polagrid.evaluate --csv results/baseline_compare.csv`. Only its numbers go into the
table. A method missing from the CSV is written as null and the page shows "not measured".
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE.parent.parent / "edge_ai" / "results" / "baseline_compare.csv"
# page label -> CSV method name
METHODS = {
    "AI (1)+(2) probe": "PolaGrid AI (1)+(2)",
    "AI (3) predict": "PolaGrid AI (3) predict",
    "Fixed open": "B0 fixed open",
    "Blinds": "B1 blind",
    "Time schedule": "B2 schedule",
}
FIELDS = ["glare_h", "under_lit_h", "mean_desk_lux", "servo_moves"]


def build(rows):
    by = {r["method"]: r for r in rows}
    out = []
    for label, name in METHODS.items():
        r = by.get(name)
        out.append({"method": label, **{k: (float(r[k]) if r else None) for k in FIELDS}})
    any_row = next(iter(by.values()))
    return {
        "source": "sw/edge_ai/results/baseline_compare.csv",
        "made_by": "python -m polagrid.evaluate --csv (re-run 2026-10-16)",
        "test_days": int(any_row["test_days"]), "train_days": int(any_row["train_days"]),
        "limits": "Simulated room (12 cells, 2 desks, physics model), not measured on hardware. "
                  "Per-day averages; desk-hours are summed over both desks.",
        "rows": out,
    }


if __name__ == "__main__":
    with open(SRC, newline="", encoding="utf-8") as f:
        data = build(list(csv.DictReader(f)))
    # self-check: the four methods the demo compares are all measured in the CSV
    assert all(r["glare_h"] is not None for r in data["rows"]), "a compared method is missing from the CSV"
    assert build([{"method": "B1 blind", **{k: "1" for k in FIELDS}, "test_days": "1", "train_days": "1"}])["rows"][0]["glare_h"] is None
    (HERE / "compare.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print("wrote", HERE / "compare.json", "from", SRC)
