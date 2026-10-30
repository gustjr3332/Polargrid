"""Summarise results/in_outage_<day>.csv by phase (base / IN down / after restart), using IN_STOP and IN_START from the events log.
    python3 tools/in_outage_report.py results/in_outage_1027"""
import csv, statistics as st, sys
from collections import Counter

pre = sys.argv[1]
ev = {l.split()[1]: float(l.split()[0]) for l in open(pre + ".events.log") if l[:1].isdigit() and len(l.split()) > 1}
rows = list(csv.DictReader(open(pre + ".csv")))
ph = lambda t: "base" if t < ev["IN_STOP"] else "down" if t < ev["IN_START"] else "after"
q = lambda v, p: sorted(v)[min(len(v) - 1, int(len(v) * p))]
for p in ("base", "down", "after"):
    print("==", p)
    for k in ("cmd", "mn", "viaIN", "cmdIN"):
        r = [x for x in rows if x["kind"] == k and ph(float(x["t"])) == p]
        ms = [float(x["ms"]) / (1000 if k == "cmd" else 1) for x in r if x["ms"] and x["status"] in ("ok", "200", "201")]
        print(f"{k:6}{len(r):4} {dict(Counter(x['status'] for x in r))}" + (f" p50={st.median(ms):.2f} p95={q(ms, .95):.2f} max={max(ms):.2f}" + (" s" if k == "cmd" else " ms") if ms else ""))
