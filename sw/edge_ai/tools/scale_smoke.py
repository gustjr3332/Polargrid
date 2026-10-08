"""스케일 스모크 테스트: 칸 N개를 CSE에 등록한 뒤(설치 단계), 운영 트래픽(CIN 쓰기)을 측정.
사용: python tools/scale_smoke.py --n 1000 --workers 20 [--layout ae|zone] [--writes 3000]
  --layout ae   : 칸마다 AE 1개   /cse-in/{run}panel{i}/angle
  --layout zone : zone마다 AE 1개 /cse-in/{run}zone{z}/panel{i}/angle  (--zone-size 칸씩)
가정: ACME 기본 설정(포트 8080, cseName cse-in). AE originator는 C{AE이름}으로 자동 생성.
ACME 실행: docker run -d --name acme-cse -p 8080:8080 ankraft/acme-onem2m-cse
"""
import argparse, json, random, statistics, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
import requests

_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def hdr(origin, ty=None):
    h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3",
         "Accept": "application/json"}
    h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
    return h


def timed(fn):
    t0 = time.perf_counter()
    r = fn()
    return r, time.perf_counter() - t0


def create_ae(base, rn):
    # AE마다 고유 originator 필요 (ACME는 같은 originator의 중복 등록을 403으로 거부)
    return sess().post(base, headers=hdr(f"C{rn}", 2),
                       data=json.dumps({"m2m:ae": {"rn": rn, "api": "Npolagrid", "rr": False, "srv": ["3"]}}))


def create_cnt(url, orig, rn):
    return sess().post(url, headers=hdr(orig, 3), data=json.dumps({"m2m:cnt": {"rn": rn}}))


def create_cin(url, orig, con):
    return sess().post(url, headers=hdr(orig, 4), data=json.dumps({"m2m:cin": {"con": con}}))


def setup_panel(a, i):
    """칸 1개 설치: 등록(AE 또는 panel CNT) → angle CNT → 첫 CIN. 요청 3건."""
    t = {}
    if a.layout == "ae":
        rn = f"{a.run}panel{i}"
        orig, parent = f"C{rn}", f"{a.base}/{rn}"
        r, t["reg"] = timed(lambda: create_ae(a.base, rn))
    else:
        zone = f"{a.run}zone{i // a.zone_size}"
        orig, parent = f"C{zone}", f"{a.base}/{zone}/panel{i}"
        r, t["reg"] = timed(lambda: create_cnt(f"{a.base}/{zone}", orig, f"panel{i}"))
    if r.status_code != 201:
        return None, f"reg {r.status_code} {r.text[:120]}"
    r, t["cnt"] = timed(lambda: create_cnt(parent, orig, "angle"))
    r2, t["cin"] = timed(lambda: create_cin(f"{parent}/angle", orig, "45"))
    if r.status_code != 201 or r2.status_code != 201:
        return None, f"CNT/CIN {r.status_code}/{r2.status_code}"
    return (t, (orig, f"{parent}/angle")), None


def steady_write(target):
    orig, url = target
    r, dt = timed(lambda: create_cin(url, orig, str(random.randrange(0, 91, 15))))
    return dt if r.status_code == 201 else None


def pct(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(len(v) * p))]


def summary(label, v):
    v = [x * 1000 for x in v]
    print(f"  {label}: p50={statistics.median(v):.0f}ms p95={pct(v, .95):.0f}ms max={max(v):.0f}ms")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--layout", choices=["ae", "zone"], default="ae")
    ap.add_argument("--zone-size", type=int, default=100)
    ap.add_argument("--writes", type=int, default=0, help="설치 후 운영 단계 CIN 쓰기 횟수 (0이면 생략)")
    ap.add_argument("--base", default="http://localhost:8080/cse-in")
    ap.add_argument("--run", default=f"r{int(time.time()) % 100000}",
                    help="리소스 이름 접두사. 재실행 시 이름 충돌 방지")
    a = ap.parse_args()

    if a.layout == "zone":
        zones = range((a.n + a.zone_size - 1) // a.zone_size)
        bad = [z for z in zones if create_ae(a.base, f"{a.run}zone{z}").status_code != 201]
        if bad:
            raise SystemExit(f"zone AE 등록 실패: {bad}")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda i: setup_panel(a, i), range(a.n)))
    wall = time.perf_counter() - t0
    ok = [r for r, e in res if r]; errs = [e for r, e in res if e]
    print(f"[setup] layout={a.layout} N={a.n} ok={len(ok)} fail={len(errs)} wall={wall:.1f}s "
          f"throughput={3 * len(ok) / wall:.0f} req/s")
    for k in ("reg", "cnt", "cin"):
        if ok:
            summary(k, [t[k] for t, _ in ok])
    for e in errs[:5]: print("  ERR", e)

    if a.writes and ok:
        targets = [random.choice(ok)[1] for _ in range(a.writes)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(a.workers) as ex:
            lat = list(ex.map(steady_write, targets))
        wall = time.perf_counter() - t0
        good = [x for x in lat if x is not None]
        print(f"[steady] writes={a.writes} ok={len(good)} wall={wall:.1f}s throughput={len(good) / wall:.0f} req/s")
        if good:
            summary("cin", good)
