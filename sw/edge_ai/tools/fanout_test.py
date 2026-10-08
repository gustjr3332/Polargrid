"""구역 명령 전달 지연 측정 (Week 0 관문: MN 1개 · 100칸 · p95 ≤ 5s).
칸 N개(AE + command CNT + SUB)를 만들고, 칸마다 SUB 알림을 받는 HTTP 서버를 이 프로세스 안에 띄운다.
명령 1회 = 구역 GRP의 fopt에 CIN 1건 POST → 모든 칸에 알림이 도착할 때까지의 시간.
비교용으로 같은 명령을 칸마다 개별 POST(동시 20)하는 방식도 잰다.
사용: python3 tools/fanout_test.py --base http://127.0.0.1:3001/TinyIoT-mn001 --n 100 --rounds 20
"""
import argparse, json, statistics, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

_local = threading.local()
arrivals = {}            # 명령 id -> {칸 번호: 도착 시각}
lock = threading.Lock()


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def hdr(origin, ty=None):
    h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3", "Accept": "application/json"}
    h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
    return h


class Notify(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        t = time.perf_counter()
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.send_header("Content-Length", "0")
        self.end_headers()
        try:
            sgn = json.loads(body)["m2m:sgn"]
            con = json.loads(sgn["nev"]["rep"]["m2m:cin"]["con"])
        except Exception:
            return                                   # 구독 확인(vrq) 등 명령이 아닌 알림
        panel = int(self.path.strip("/").lstrip("p"))
        with lock:
            arrivals.setdefault(con["cmd"], {})[panel] = t

    def log_message(self, *a):
        pass


def post(url, orig, body, ty):
    return sess().post(url, headers=hdr(orig, ty), data=json.dumps(body))


def wait_all(cmd, n, timeout=30):
    t_end = time.perf_counter() + timeout
    while time.perf_counter() < t_end:
        with lock:
            got = dict(arrivals.get(cmd, {}))
        if len(got) >= n:
            return got
        time.sleep(0.005)
    return got


def pct(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(len(v) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3001/TinyIoT-mn001")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--run", default=f"f{int(time.time()) % 100000}")
    a = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Notify)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cse = a.base.rsplit("/", 1)[1]

    def setup(i):
        rn, orig = f"{a.run}p{i}", f"C{a.run}p{i}"
        r1 = post(a.base, orig, {"m2m:ae": {"rn": rn, "api": "Npolagrid", "rr": True, "srv": ["3"],
                                             "poa": [f"http://127.0.0.1:{a.port}/p{i}"]}}, 2)
        r2 = post(f"{a.base}/{rn}", orig, {"m2m:cnt": {"rn": "command", "mni": 10}}, 3)
        r3 = post(f"{a.base}/{rn}/command", orig, {"m2m:sub": {"rn": "s", "nu": [f"http://127.0.0.1:{a.port}/p{i}"],
                                                                "enc": {"net": [3]}, "nct": 1}}, 23)
        bad = [r for r in (r1, r2, r3) if r.status_code != 201]
        return f"{cse}/{rn}/command" if not bad else f"ERR {bad[0].status_code} {bad[0].text[:150]}"

    t0 = time.perf_counter()
    with ThreadPoolExecutor(20) as ex:
        mids = list(ex.map(setup, range(a.n)))
    errs = [m for m in mids if m.startswith("ERR")]
    print(f"[setup] N={a.n} ok={a.n - len(errs)} wall={time.perf_counter() - t0:.1f}s")
    for e in errs[:3]:
        print(" ", e)
    if errs:
        return

    g = post(a.base, "CAdmin", {"m2m:grp": {"rn": f"{a.run}zone", "mt": 3, "mnm": a.n, "mid": mids}}, 9)
    print(f"[grp] {g.status_code} {'' if g.status_code == 201 else g.text[:200]}")

    def run(mode, k):
        cmd = f"{mode}{k}"
        body = {"m2m:cin": {"con": json.dumps({"cmd": cmd, "angle": (k * 15) % 90})}}
        t = time.perf_counter()
        if mode == "grp":
            r = post(f"{a.base}/{a.run}zone/fopt", "CAdmin", body, 4)
            ok = r.status_code in (200, 201)
        else:
            with ThreadPoolExecutor(20) as ex:
                rs = list(ex.map(lambda m: post(f"{a.base.rsplit('/', 1)[0]}/{m}", "CAdmin", body, 4), mids))
            ok = all(r.status_code == 201 for r in rs)
        got = wait_all(cmd, a.n)
        lat = sorted(v - t for v in got.values())
        return ok, len(got), lat

    for mode in ("grp", "each"):
        if mode == "grp" and g.status_code != 201:
            continue
        alls, lasts, miss = [], [], 0
        for k in range(a.rounds):
            ok, n, lat = run(mode, k)
            miss += a.n - n
            alls += lat
            if lat:
                lasts.append(lat[-1])
            time.sleep(0.3)
        if lasts:
            print(f"[{mode}] rounds={a.rounds} missing={miss} "
                  f"per-panel p50={statistics.median(alls) * 1000:.0f}ms p95={pct(alls, .95) * 1000:.0f}ms | "
                  f"zone-complete p50={statistics.median(lasts) * 1000:.0f}ms p95={pct(lasts, .95) * 1000:.0f}ms "
                  f"max={max(lasts) * 1000:.0f}ms")
        else:
            print(f"[{mode}] no notifications received")


if __name__ == "__main__":
    main()
