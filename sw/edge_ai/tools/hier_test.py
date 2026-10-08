"""1,000칸 계층 측정: MN-CSE M개 × 칸 P개. 구역(MN)마다 GRP 1개, 칸마다 command CNT + SUB.
명령 1회 = M개 구역에 동시에 GRP fopt POST → M×P칸 모두 알림이 도착할 때까지의 시간.
  edge : 각 MN에 직접 보냄 (구역 제어 앱이 엣지/MEC에 있는 경우)
  in   : IN-CSE를 거쳐 MN으로 보냄 (/~/{csi}/{cse}/{grp}/fopt, 중앙 제어 앱인 경우)
--bg 로 배경 부하(칸 조도 CIN, 초당 건수)를 같이 걸 수 있다. 1,000칸 × 60초 주기 ≈ 17 req/s.
사용: python3 tools/hier_test.py --mns 10 --per 100 --rounds 20 --modes edge,in --bg 17
전제: IN(3000)과 mn001..mnM(3001..)이 떠 있음 (tools/run_in.sh, sim/nodes.sh start M)
"""
import argparse, json, multiprocessing as mp, random, re, statistics, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

IN_BASE = "http://127.0.0.1:3000"
_local = threading.local()
arrivals, lock = {}, threading.Lock()      # 명령 id -> {(구역, 칸): 도착 시각(time.time)}
# 알림 수신기와 배경 부하는 별도 프로세스로 돌린다. 한 프로세스에 몰면 파이썬 GIL이 1,000건 알림을 줄 세워
# CSE가 아니라 측정 클라이언트가 병목이 된다(첫 측정에서 확인). 프로세스 간 시각은 time.time()으로 맞춘다.


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def hdr(origin, ty=None):
    h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3", "Accept": "application/json"}
    h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
    return h


def post(url, orig, body, ty):
    return sess().post(url, headers=hdr(orig, ty), data=json.dumps(body), timeout=30)


class Notify(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    queue = None

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        t = time.time()
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.send_header("Content-Length", "0")
        self.end_headers()
        try:
            con = json.loads(json.loads(body)["m2m:sgn"]["nev"]["rep"]["m2m:cin"]["con"])
        except Exception:
            return                                   # 구독 확인(vrq) 알림
        z, p = (int(x[1:]) for x in self.path.strip("/").split("/"))
        self.queue.put((con["cmd"], z, p, t))

    def log_message(self, *a):
        pass


def serve(port, q):
    Notify.queue = q
    srv = ThreadingHTTPServer(("127.0.0.1", port), Notify)
    srv.daemon_threads = True
    srv.serve_forever()


def collect(q):
    while True:
        cmd, z, p, t = q.get()
        with lock:
            arrivals.setdefault(cmd, {})[(z, p)] = t


def background(luxes, rate, stop, ok, fail):
    """칸 조도 보고(배경 부하). 별도 프로세스, 내부 스레드 4개로 rate건/초."""
    def worker():
        s = requests.Session()
        nxt = time.time()
        while not stop.is_set():
            orig, url = random.choice(luxes)
            try:
                good = s.post(url, headers=hdr(orig, 4), timeout=30,
                              data=json.dumps({"m2m:cin": {"con": str(random.randint(200, 1200))}})).status_code == 201
            except Exception:
                good = False
            with (ok if good else fail).get_lock():
                (ok if good else fail).value += 1
            nxt += 4 / rate
            time.sleep(max(0, nxt - time.time()))
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for t in ts:
        t.start()
    stop.wait()


def mn(k):
    return f"http://127.0.0.1:{3000 + k}", f"TinyIoT-mn{k:03d}", f"id-mn{k:03d}"


def pct(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(len(v) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mns", type=int, default=10)
    ap.add_argument("--per", type=int, default=100)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--modes", default="edge,in")
    ap.add_argument("--bg", type=float, default=0, help="배경 조도 CIN 초당 건수")
    ap.add_argument("--port", type=int, default=9400)
    ap.add_argument("--run", default=f"h{int(time.time()) % 100000}")
    a = ap.parse_args()

    q = mp.Queue()
    for z in range(1, a.mns + 1):
        mp.Process(target=serve, args=(a.port + z, q), daemon=True).start()
    threading.Thread(target=collect, args=(q,), daemon=True).start()
    time.sleep(1)

    # IN은 전달할 때 originator CAdmin을 /tinyiot/CAdmin 으로 바꾼다(TS-0004). 최신 tinyIoT MN은 이것을 관리자로 보지 않아
    # IN 경유 fopt의 멤버 응답이 전부 4103이 된다. 구역마다 ACP를 만들어 command CNT와 GRP에 붙인다.
    acp = {}
    for z in range(1, a.mns + 1):
        host, cse, _ = mn(z)
        r = post(f"{host}/{cse}", "CAdmin", {"m2m:acp": {"rn": f"{a.run}acp", "pv": {"acr": [
            {"acor": ["CAdmin", "/tinyiot/CAdmin", f"C{a.run}z{z}p*"], "acop": 63}]},
            "pvs": {"acr": [{"acor": ["CAdmin"], "acop": 63}]}}}, 1)
        if r.status_code != 201:
            print(f"[acp] mn{z:03d} {r.status_code} {r.text[:150]}")
            return
        acp[z] = r.json()["m2m:acp"]["ri"]

    def setup(zp):
        z, i = zp
        host, cse, _ = mn(z)
        rn, orig = f"{a.run}p{i}", f"C{a.run}z{z}p{i}"
        nu = f"http://127.0.0.1:{a.port + z}/z{z}/p{i}"
        rs = [post(f"{host}/{cse}", orig, {"m2m:ae": {"rn": rn, "api": "Npolagrid", "rr": True, "srv": ["3"], "poa": [nu]}}, 2),
              post(f"{host}/{cse}/{rn}", orig, {"m2m:cnt": {"rn": "command", "mni": 10, "acpi": [acp[z]]}}, 3),
              post(f"{host}/{cse}/{rn}", orig, {"m2m:cnt": {"rn": "lux", "mni": 10}}, 3),
              post(f"{host}/{cse}/{rn}/command", orig, {"m2m:sub": {"rn": "s", "nu": [nu], "enc": {"net": [3]}, "nct": 1}}, 23)]
        bad = [r for r in rs if r.status_code != 201]
        return (z, f"{cse}/{rn}/command", orig, f"{host}/{cse}/{rn}/lux") if not bad else ("ERR", bad[0].status_code, bad[0].text[:150])

    zones = range(1, a.mns + 1)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(40) as ex:
        res = list(ex.map(setup, [(z, i) for z in zones for i in range(a.per)]))
    errs = [r for r in res if r[0] == "ERR"]
    print(f"[setup] {a.mns} MN x {a.per} = {len(res)} panels, ok={len(res) - len(errs)} wall={time.perf_counter() - t0:.1f}s")
    for e in errs[:3]:
        print("  ", e)
    if errs:
        return
    for z in zones:
        host, cse, _ = mn(z)
        mids = [r[1] for r in res if r[0] == z]
        g = post(f"{host}/{cse}", "CAdmin", {"m2m:grp": {"rn": f"{a.run}zone", "mt": 3, "mnm": a.per, "mid": mids, "acpi": [acp[z]]}}, 9)
        if g.status_code != 201:
            print(f"[grp] mn{z:03d} {g.status_code} {g.text[:150]}")
            return

    stop, ok, fail = mp.Event(), mp.Value("i", 0), mp.Value("i", 0)
    if a.bg:
        mp.Process(target=background, args=([(r[2], r[3]) for r in res], a.bg, stop, ok, fail), daemon=True).start()
        time.sleep(2)

    total = a.mns * a.per
    for mode in a.modes.split(","):
        def fire(z, body):
            host, cse, csi = mn(z)
            url = f"{host}/{cse}/{a.run}zone/fopt" if mode == "edge" else f"{IN_BASE}/~/{csi}/{cse}/{a.run}zone/fopt"
            r = post(url, "CAdmin", body, 4)
            bad = {m for m in re.findall(r'"rsc":(\d+)', r.text) if m != "2001"}   # 멤버 실패는 바깥 200에 가려진다
            return f"{r.status_code}" + (f" member-rsc={','.join(sorted(bad))}" if bad else "")
        dones, zone_p95s, miss, codes = [], [], 0, set()
        for k in range(a.rounds):
            cmd = f"{mode}{k}"
            body = {"m2m:cin": {"con": json.dumps({"cmd": cmd, "angle": (k * 15) % 90})}}
            t = time.time()
            with ThreadPoolExecutor(a.mns) as ex:
                codes |= set(ex.map(lambda z: fire(z, body), zones))
            t_end = time.perf_counter() + 30
            while time.perf_counter() < t_end:
                with lock:
                    got = dict(arrivals.get(cmd, {}))
                if len(got) >= total:
                    break
                time.sleep(0.005)
            miss += total - len(got)
            if got:
                dones.append(max(got.values()) - t)
                per_zone = {}
                for (z, _), v in got.items():
                    per_zone[z] = max(per_zone.get(z, 0), v - t)
                zone_p95s.append(pct(list(per_zone.values()), .95))
            time.sleep(0.5)
        if dones:
            print(f"[{mode}] rounds={a.rounds} fopt_status={sorted(codes)} missing={miss}/{a.rounds * total} | "
                  f"all-{total}-panels complete p50={statistics.median(dones) * 1000:.0f}ms "
                  f"p95={pct(dones, .95) * 1000:.0f}ms max={max(dones) * 1000:.0f}ms | "
                  f"zone-complete p95 (median over rounds)={statistics.median(zone_p95s) * 1000:.0f}ms")
        else:
            print(f"[{mode}] no notifications (fopt_status={sorted(codes)})")
    stop.set()
    if a.bg:
        print(f"[bg] lux CIN ok={ok.value} fail={fail.value}")


if __name__ == "__main__":
    main()
