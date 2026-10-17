"""AI (3) with real skies, repeated runs: KMA ASOS station kt vs Open-Meteo (ERA5) kt, location transfer, sensor noise.

Every cell is run over 3 disjoint sets of 20 test days (2025-01-01 + 3/9/15 + 18k, odd offsets) and, where the
training data or model is random, 3 seeds (60 d / 30 d training dates start at offset 2*seed; RF random_state=seed).
Training dates are even offsets only, so they never overlap a test date. Needs data/weather/kma_<site>_2025.csv
(python -m polagrid.weather fetch-kma).

    python tools/ai3_weather_kma.py > results/ai3_weather_kma_1017.txt
"""
import functools
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai3_weather import fit, rows, score, site_room  # noqa: E402
from polagrid import evaluate, virtual, weather  # noqa: E402

JAN1 = date(weather.YEAR, 1, 1)
weather.load_kt = functools.lru_cache(None)(weather.load_kt)  # shortcut: parse each CSV once per run
SEEDS, SETS, MARGIN = (0, 1, 2), (0, 1, 2), virtual.AI3_MARGIN_LUX
_rows = {}


def test_days(site, source, j):
    return weather.real_days(site, JAN1 + timedelta(days=3 + 6 * j), 20, 18, source=source)


def train_days(site, source, n, seed):
    if n == 180:
        return weather.real_days(site, JAN1, 180, 2, source=source)
    return weather.real_days(site, JAN1 + timedelta(days=2 * seed), n, 360 // n, source=source)


def data(site, source, days, extra):
    """Teacher rows (cached per day); base features = first 6 columns."""
    room, out = site_room(site), []
    for d, c in days:
        key = (site, source, d)
        if key not in _rows:
            _rows[key] = rows(room, d, c, MARGIN, True)
        out += _rows[key]
    x = np.array([x if extra else x[:6] for x, _ in out])
    return x, np.array([a for _, a in out])


def stats(name, runs):
    r = np.array(runs)
    g = r[:, 0]
    print(f"{name:<44}{len(r):>3}  {g.mean():5.2f} +- {g.std():4.2f} [{g.min():4.2f}-{g.max():4.2f}]"
          f"  {r[:, 1].mean():6.2f} +- {r[:, 1].std():4.2f}  {r[:, 2].mean():5.0f}  {r[:, 3].mean():5.0f} +- {r[:, 3].std():3.0f}",
          flush=True)
    return g.mean()


def header(title):
    print(f"\n## {title}\n{'method':<44}{'n':>3}  {'glare h mean +- sd [min-max]':<28}  {'under-lit h':<14}"
          f"  {'lux':>5}  {'moves':>11}", flush=True)


def refs(site, source):
    room = site_room(site)
    ctl = {"fixed open": lambda: evaluate.fixed_open, "AI (1)+(2) probe": lambda: evaluate.polagrid_probe(room.n_cells)}
    out = {k: [] for k in ctl}
    for j in SETS:
        for k, r in evaluate.compare(room, test_days(site, source, j), ctl).items():
            out[k].append((r["glare_h"], r["dark_h"], r["mean_lux"], r["moves"]))
    for k, v in out.items():
        stats(k, v)


def runs(kind, train, extra, test_site, test_src, noise=0.0):
    """train: seed -> list of (site, source, days). Fits once per seed when the data or model differs by seed."""
    out, room = [], site_room(test_site)
    for seed in SEEDS:
        parts = [data(s, src, d, extra) for s, src, d in train(seed)]
        x, a = np.vstack([p[0] for p in parts]), np.vstack([p[1] for p in parts])
        model = fit(kind, x, a, seed)
        out += [score(model, room, test_days(test_site, test_src, j), extra, noise, seed) for j in SETS]
        dates = lambda k: [(st, src, [d for d, _ in ds]) for st, src, ds in train(k)]
        if kind == "GBR" and dates(0) == dates(1):
            break                                       # deterministic model on identical data: one fit is enough
    return out


def main():
    t0 = time.time()
    print("# AI (3), real skies, 2026-10-17. kt = hourly GHI / Haurwitz clear sky, cloud = 1 - kt, sun >= 5 deg.")
    print("# KMA: ASOS icsr (MJ/m2 per hour, x 277.8 = W/m2), Seoul 108, Sejong 239. Open-Meteo: ERA5 GHI (W/m2).")
    print("# 12 cells, 2 desks, south window, margin 2500 lux. Per-day values, desk-hours summed over 2 desks.")
    print("# n = runs (3 disjoint 20-day test sets x seeds). sd = population std over runs. Virtual physics only.")

    best = {}
    for src_test in ("kma", "openmeteo"):
        header(f"Reference, Seoul, test sky = {src_test}")
        refs("seoul", src_test)

    for train_src, test_src in (("kma", "kma"), ("openmeteo", "kma"), ("openmeteo", "openmeteo")):
        header(f"Seoul: train sky {train_src}, test sky {test_src}")
        for n in (60, 180):
            for kind in ("RF", "GBR"):
                for extra in (False, True):
                    name = f"real {n}d {kind} {'+kt,kt-1h' if extra else 'base'}"
                    m = stats(name, runs(kind, lambda s: [("seoul", train_src, train_days("seoul", train_src, n, s))],
                                         extra, "seoul", test_src))
                    if train_src == test_src == "kma":
                        best[(n, kind, extra)] = m
        if test_src == "kma" and train_src == "kma":
            for kind in ("HGB", "RF"):
                synth = lambda s: [("seoul", f"synthetic{s}", evaluate.days(JAN1, 60, 6, seed=s + 1))]
                best[("synthetic", kind)] = stats(f"synthetic 60d {kind} base (old AI (3) data)",
                                                  runs(kind, synth, False, "seoul", "kma"))

    header("Location transfer: test Sejong (KMA 239), train sky kma")
    refs("sejong", "kma")
    for extra in (False, True):
        f = "+kt,kt-1h" if extra else "base"
        sj = lambda n: (lambda s: [("sejong", "kma", train_days("sejong", "kma", n, s))])
        se = lambda n: (lambda s: [("seoul", "kma", train_days("seoul", "kma", n, s))])
        stats(f"Seoul 60d RF {f}", runs("RF", se(60), extra, "sejong", "kma"))
        stats(f"Seoul 180d RF {f}", runs("RF", se(180), extra, "sejong", "kma"))
        stats(f"Sejong 30d RF {f}", runs("RF", sj(30), extra, "sejong", "kma"))
        stats(f"Sejong 60d RF {f}", runs("RF", sj(60), extra, "sejong", "kma"))
        stats(f"Sejong 180d RF {f}", runs("RF", sj(180), extra, "sejong", "kma"))
        for n in (30, 60):
            stats(f"Seoul 180d + Sejong {n}d RF {f}",
                  runs("RF", lambda s, n=n: se(180)(s) + sj(n)(s), extra, "sejong", "kma"))
        stats(f"reverse: Seoul test, Sejong 180d RF {f}", runs("RF", sj(180), extra, "seoul", "kma"))

    header("Sensor noise on the outdoor-lux feature, Seoul, real 180d RF base, kma")
    for noise in (0.05, 0.2):
        stats(f"noise {noise:.0%}", runs("RF", lambda s: [("seoul", "kma", train_days("seoul", "kma", 180, s))],
                                          False, "seoul", "kma", noise))

    real = {k: v for k, v in best.items() if k[0] != "synthetic"}
    (n, kind, extra), g = min(real.items(), key=lambda kv: kv[1])
    old = best[("synthetic", "HGB")]
    print(f"\n# best KMA-trained cell: real {n}d {kind} {'+kt' if extra else 'base'}, glare {g:.2f} h vs synthetic HGB {old:.2f} h")
    if g < old:
        x, a = data("seoul", "kma", train_days("seoul", "kma", n, 0), extra)
        out = virtual.MODEL_DIR / "predictor_3x4_kma_seoul.joblib"
        joblib.dump({"model": fit(kind, x, a, 0), "rows": 3, "cols": 4, "days": n, "weather": "kma_seoul_2025",
                     "features": "base+kt,kt-1h" if extra else "base", "margin": MARGIN}, out)
        print(f"# saved {out.name}")
    print(f"# total {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
