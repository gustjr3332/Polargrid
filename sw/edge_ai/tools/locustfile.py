"""PolaGrid oneM2M 부하 시나리오 (Locust 초안).

Locust 사용자 1명 = 편광 칸(panel) 1개. 시작 시 AE와 컨테이너(lux, angle, command)를 만들고,
이후 조도 보고, 각도 변경 기록, 명령 확인을 반복한다. ZoneController는 관리자 권한으로
임의 칸에 명령을 쓴다 (zone 일괄 제어의 부하 프록시).

실행 (ACME가 localhost:8080에 떠 있어야 함):
  웹 UI:   python -m locust -f tools/locustfile.py --host http://localhost:8080
  헤드리스: python -m locust -f tools/locustfile.py --host http://localhost:8080 \
             --headless -u 200 -r 20 -t 2m --csv results/locust_200

환경변수:
  LUX_PERIOD  조도 보고 주기(초, 기본 60). 부하를 키우려면 줄인다.
  CSE_NAME    CSE 이름 (기본 cse-in)
"""
import json, os, random, time, uuid

from locust import FastHttpUser, between, constant_pacing, task

CSE = "/" + os.getenv("CSE_NAME", "cse-in")
LUX_PERIOD = float(os.getenv("LUX_PERIOD", "60"))
RUN = f"L{int(time.time()) % 100000}"
_panels = []  # 등록된 칸 이름 (ZoneController가 명령 대상으로 사용)


def hdr(origin, ty=None):
    return {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex, "X-M2M-RVI": "3",
            "Accept": "application/json",
            "Content-Type": "application/json" + (f";ty={ty}" if ty else "")}


class Panel(FastHttpUser):
    weight = 100
    wait_time = constant_pacing(LUX_PERIOD)
    _seq = 0

    def on_start(self):
        Panel._seq += 1
        self.rn = f"{RUN}p{Panel._seq}"
        self.orig = f"C{self.rn}"
        self.angle = 45
        r = self.client.post(CSE, name="register AE", headers=hdr(self.orig, 2),
                             data=json.dumps({"m2m:ae": {"rn": self.rn, "api": "Npolagrid",
                                                         "rr": False, "srv": ["3"]}}))
        if r.status_code != 201:
            self.stop()
            return
        for c in ("lux", "angle", "command"):
            self.client.post(f"{CSE}/{self.rn}", name="create CNT", headers=hdr(self.orig, 3),
                             data=json.dumps({"m2m:cnt": {"rn": c, "mni": 10}}))
        _panels.append(self.rn)

    @task(10)
    def report_lux(self):
        lux = random.randint(200, 1200)
        self.client.post(f"{CSE}/{self.rn}/lux", name="CIN lux", headers=hdr(self.orig, 4),
                         data=json.dumps({"m2m:cin": {"con": str(lux)}}))

    @task(2)
    def report_angle_if_changed(self):
        # 변경 시에만 기록 (계획서 3절 설계 원칙). 약 절반은 변화 없음으로 가정
        new = max(0, min(90, self.angle + random.choice([-10, 0, 0, 10])))
        if new != self.angle:
            self.angle = new
            self.client.post(f"{CSE}/{self.rn}/angle", name="CIN angle", headers=hdr(self.orig, 4),
                             data=json.dumps({"m2m:cin": {"con": str(new)}}))

    @task(3)
    def poll_command(self):
        # 폴링 방식 명령 확인. 실제 구현은 Subscription/Notification으로 바꿀 예정 (비교 기준선)
        with self.client.get(f"{CSE}/{self.rn}/command/la", name="GET command/la",
                             headers=hdr(self.orig), catch_response=True) as r:
            if r.status_code in (200, 404):  # 404 = 아직 명령 없음, 정상
                r.success()


class ZoneController(FastHttpUser):
    weight = 1
    wait_time = between(1, 3)

    @task
    def send_command(self):
        if not _panels:
            return
        target = random.choice(_panels)
        self.client.post(f"{CSE}/{target}/command", name="CIN command (admin)",
                         headers=hdr("CAdmin", 4),
                         data=json.dumps({"m2m:cin": {"con": json.dumps(
                             {"angle": random.randrange(0, 91, 15)})}}))
