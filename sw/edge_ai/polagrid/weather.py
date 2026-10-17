"""Real hourly solar data for the virtual room: Open-Meteo archive (ERA5 reanalysis), cached as CSV.

Weather data by Open-Meteo.com (https://open-meteo.com/, CC BY 4.0, free for non-commercial use only).
The clear-sky index kt = measured GHI / clear-sky GHI (Haurwitz model) becomes the physics `cloud` input,
one value per hour, so a simulated day follows a real day's sky.

    python -m polagrid.weather fetch            # writes data/weather/<site>_2025.csv
    python -m polagrid.weather fetch-kma        # KMA ASOS (needs KMA_SERVICE_KEY), data/weather/kma_<site>_2025.csv
"""
import csv
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from .physics import KST, sun_position

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "weather"
SITES = {"seoul": (37.5503, 127.0731), "sejong": (36.48, 127.29), "jeju": (33.51, 126.53)}
YEAR = 2025
MIN_ALT = 5.0  # below this sun altitude the clear-sky denominator is too small, kt is not used
KMA_STN = {"seoul": 108, "sejong": 239}  # ASOS station ids, names checked against the API (stnNm)
VARS = ["shortwave_radiation", "direct_radiation", "diffuse_radiation", "cloud_cover"]


def path(site, year=YEAR):
    return DATA_DIR / f"{site}_{year}.csv"


def fetch(site, year=YEAR):
    lat, lon = SITES[site]
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat}&longitude={lon}&start_date={year}-01-01&end_date={year}-12-31"
           f"&hourly={','.join(VARS)}&timezone=Asia%2FSeoul")
    with urllib.request.urlopen(url, timeout=60) as r:
        h = json.load(r)["hourly"]
    p = path(site, year)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_kst", "ghi_wm2", "direct_wm2", "diffuse_wm2", "cloud_pct"])  # radiation: mean of the hour before
        for row in zip(h["time"], *(h[v] for v in VARS)):
            w.writerow([row[0]] + ["" if v is None else round(v) for v in row[1:]])
    return p


MJ_H_TO_WM2 = 1e6 / 3600  # MJ/m2 summed over one hour -> mean W/m2 of that hour
KMA_URL = "https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"


def kma_key():
    """data.go.kr service key from KMA_SERVICE_KEY (process env, else the Windows user env). Never print it."""
    k = os.environ.get("KMA_SERVICE_KEY")
    if not k and os.name == "nt":
        k = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Environment]::GetEnvironmentVariable('KMA_SERVICE_KEY','User')"],
                           capture_output=True, text=True).stdout.strip()
    if not k:
        raise SystemExit("KMA_SERVICE_KEY is not set")
    return k


def kma_page(stn, start, end, page, rows=999):
    """One page of KMA ASOS hourly data (dates YYYYMMDD). Returns the response body dict."""
    q = urllib.parse.urlencode({"pageNo": page, "numOfRows": rows, "dataType": "JSON", "dataCd": "ASOS",
                                "dateCd": "HR", "startDt": start, "startHh": "00", "endDt": end, "endHh": "23",
                                "stnIds": stn})
    try:
        with urllib.request.urlopen(f"{KMA_URL}?serviceKey={kma_key()}&{q}", timeout=120) as r:
            res = json.load(r)["response"]
    except Exception as e:
        raise RuntimeError(f"KMA request failed ({type(e).__name__})") from None   # the URL holds the key
    if res["header"]["resultCode"] != "00":
        raise RuntimeError(f"KMA error {res['header']['resultCode']} {res['header']['resultMsg']}")
    return res["body"]


def fetch_kma(site, year=YEAR):
    """All hours of one year for KMA_STN[site], paged, cached as data/weather/kma_<site>_<year>.csv."""
    stn, items, page = KMA_STN[site], [], 1
    while True:
        body = kma_page(stn, f"{year}0101", f"{year}1231", page)
        items += body["items"]["item"] if body["items"] else []
        if len(items) >= body["totalCount"] or not body["items"]:
            break
        page += 1
    p = DATA_DIR / f"kma_{site}_{year}.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tm_kst", "stn_id", "icsr_mj", "cloud_tenths"])   # icsr: MJ/m2 over the hour ending at tm
        for it in items:
            w.writerow([it["tm"], it["stnId"], it.get("icsr", ""), it.get("dc10Tca", "")])
    return p, len(items), items[0].get("stnNm")


def clear_ghi(alt):
    """Haurwitz clear-sky global horizontal irradiance, W/m2."""
    s = math.sin(math.radians(alt))
    return 1098 * s * math.exp(-0.057 / s) if s > 0 else 0.0


def load_kt(site, year=YEAR, source="openmeteo"):
    """{date: [24 kt values]} where index h covers h:00-h+1:00 KST; low-sun hours take the nearest valid hour.

    source "openmeteo" (ERA5 GHI, W/m2) or "kma" (ASOS icsr, MJ/m2 per hour). Both label a value with the end of
    its hour; checked 2025 Seoul/Sejong: best hourly match at zero shift, sum ratio Open-Meteo/KMA 283 and 281.
    """
    lat, lon = SITES[site]
    p, tcol, vcol, scale = ((DATA_DIR / f"kma_{site}_{year}.csv", "tm_kst", "icsr_mj", MJ_H_TO_WM2) if source == "kma"
                            else (path(site, year), "time_kst", "ghi_wm2", 1.0))
    days = {}
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            end = datetime.fromisoformat(r[tcol]).replace(tzinfo=KST)
            start = end - timedelta(hours=1)
            alt = sun_position(start + timedelta(minutes=30), lat, lon)[0]
            kt = None
            if alt >= MIN_ALT and r[vcol] != "":
                kt = min(1.2, float(r[vcol]) * scale / clear_ghi(alt))
            days.setdefault(start.date(), [None] * 24)[start.hour] = kt
    out = {}
    for d, kts in days.items():
        valid = [i for i, k in enumerate(kts) if k is not None]
        if valid:
            out[d] = [kts[min(valid, key=lambda v: abs(v - i))] for i in range(24)]
    return out


def cloud_of(kts):
    """Physics cloud input for one day: t -> 1 - kt of that hour, clipped to 0..1.

    shortcut: cloud = 1 - kt keeps direct beam ~ kt; real overcast hours have almost no beam, swap to
    Open-Meteo direct/diffuse if the beam share matters.
    """
    return lambda t: min(1.0, max(0.0, 1.0 - kts[t.hour]))


def real_days(site, start, count, every, year=YEAR, source="openmeteo"):
    """[(date, cloud function)] like evaluate.days, but with the real sky of each date (missing dates skipped)."""
    kt = load_kt(site, year, source)
    picks = [start + timedelta(days=i * every) for i in range(count)]
    return [(d, cloud_of(kt[d])) for d in picks if d in kt]


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        for s in SITES:
            print(fetch(s))
    elif sys.argv[1:] == ["fetch-kma"]:
        for s in KMA_STN:
            print(fetch_kma(s)[:2])
