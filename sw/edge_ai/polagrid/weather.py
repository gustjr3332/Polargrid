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
    p, tcol, vcol, scale = ((DATA_DIR / f"kma_{site}_{year}.csv", "tm_kst", "icsr_mj", MJ_H_TO_WM2) if source == "kma"
                            else (path(site, year), "time_kst", "ghi_wm2", 1.0))
    with open(p, encoding="utf-8") as f:
        return kt_days(site, ((r[tcol], None if r[vcol] == "" else float(r[vcol]) * scale) for r in csv.DictReader(f)))


def kt_days(site, hours):
    """{date: [24 kt]} from (end-of-hour KST time string, mean W/m2 of that hour or None) pairs."""
    lat, lon = SITES[site]
    days = {}
    for end, wm2 in hours:
        start = datetime.fromisoformat(end).replace(tzinfo=KST) - timedelta(hours=1)
        alt = sun_position(start + timedelta(minutes=30), lat, lon)[0]
        kt = min(1.2, wm2 / clear_ghi(alt)) if alt >= MIN_ALT and wm2 is not None else None
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


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def forecast_kt(site, day, timeout=10):
    """24 hourly kt of `day` from the Open-Meteo forecast (no key), or None when offline or out of range.

    shortwave_radiation is the mean of the preceding hour, the same convention as the archive.
    """
    lat, lon = SITES[site]
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": "shortwave_radiation",
                                "timezone": "Asia/Seoul", "start_date": day, "end_date": day + timedelta(days=1)})
    try:
        with urllib.request.urlopen(f"{FORECAST_URL}?{q}", timeout=timeout) as r:
            h = json.load(r)["hourly"]
        return kt_days(site, zip(h["time"], h["shortwave_radiation"])).get(day)
    except Exception as e:                       # the loop must keep running without a forecast
        print(f"[weather] forecast unavailable ({type(e).__name__}); using the constant cloud", file=sys.stderr)
        return None


def sky(site, day, source, cloud=0.0):
    """Physics cloud input for one closed-loop day: a constant, or the hourly kt of a real or forecast sky.

    source: "const", "kma"/"openmeteo" (cached 2025 archive, `day` must be in it), "forecast" (live).
    Falls back to the constant when the day has no data.
    """
    if source == "const":
        return cloud
    kts = forecast_kt(site, day) if source == "forecast" else load_kt(site, day.year, source).get(day)
    if kts is None:
        print(f"[weather] no {source} sky for {site} {day}; using cloud {cloud}", file=sys.stderr)
        return cloud
    return cloud_of(kts)


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
