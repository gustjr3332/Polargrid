"""One zone of virtual cells on a oneM2M CSE (an MN-CSE), plus the zone controller (the MEC app).

Resource tree per zone, all under the MN:
  {run}env/sun, {run}env/desks      environment AE: sun and outdoor light, desk sensor readings
  {run}p{i}/command, /state         one AE per cell: command CNT (SUB -> this zone), state FlexContainer
  {run}ctl/grp                      controller AE's GRP of every cell's command CNT: one request commands the zone

A command is one CIN {"cmd": id, "angles": [per-cell angles]} fanned out by the GRP; each cell reads its own
entry. When all cells have applied a command, the desk sensor reports lux with the same cmd id, which is how
the controller learns the command took effect. The controller talks to the CSE only.

Data interoperability: a cell's state is a standard SDT FlexContainer, cod:opeLl (TS-0023 ModuleClass openLevel,
0 closed .. 100 open = 100 cos^2(angle)), which the CSE validates. Containers carry labels polagrid/<run>/command and
polagrid/<run>/state, so the controller builds its group and a viewer finds the cells by discovery (fu=1), not by name.

Access control: CAdmin only provisions the ACPs. At run time every party uses its own AE originator:
  cell i      full rights on its own containers, nothing on other cells
  controller  create/retrieve/subscribe on cells and env (sends commands, reads sun, subscribes to desks)
  viewer      retrieve/subscribe/discover only (dashboard, BMS mock)
  env sensor  full rights on sun and desks
The controller and viewer are also listed with the IN's CSE-ID prefix, because the IN rewrites a forwarded
originator C.. to /tinyiot/C.. and the MN checks that form.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import math

import numpy as np

from .onem2m import Receiver, _headers
from .physics import simulate, sun_position, window_lux

ADMIN = "CAdmin"
IN_CSI = "/tinyiot"  # CSE-ID the IN puts in front of originators it forwards
MOVE_DEG = 1.0      # angle change that counts as a servo move
WAIT_S = 30
ALL, C, R, N, DISC = 63, 1, 2, 16, 32   # acop bits
OPEN_LEVEL = "org.onem2m.common.moduleclass.openLevel"


def roles(run):
    """Originators of the zone's parties."""
    return {"ctl": f"C{run}ctl", "view": f"C{run}view", "env": f"C{run}env"}


def make_acp(c, rn, rules):
    """Provision an ACP under the CSE base as CAdmin; rules = [(originators, acop)]. Returns its ri."""
    r = c.post("", ADMIN, {"m2m:acp": {"rn": rn, "pv": {"acr": [{"acor": o, "acop": op} for o, op in rules]},
                                       "pvs": {"acr": [{"acor": [ADMIN], "acop": ALL}]}}}, 1)
    return r.json()["m2m:acp"]["ri"]


def grant_discovery(c):
    """Let every zone's controller and viewer (C*ctl, C*view, also IN-forwarded) discover under the CSE base.
    Discovery is checked on the CSE base, whose ACP (tinyIoT: defaultACP; the CSE base itself cannot be updated)
    only admits CAdmin, so add one discovery-only rule to it. Idempotent."""
    rule = {"acor": remote("C*ctl", "C*view"), "acop": DISC}
    path = "defaultACP"
    acp = c._session().get(f"{c.host}/{c.cse}/{path}", headers=_headers(ADMIN), timeout=30).json()["m2m:acp"]
    if rule not in acp["pv"]["acr"]:
        c.put(path, ADMIN, {"m2m:acp": {"pv": {"acr": acp["pv"]["acr"] + [rule]}}})


def remote(*origs):
    """The originators plus their IN-forwarded form."""
    return [*origs, *(f"{IN_CSI}/{o}" for o in origs)]


class Zone:
    """The plant: virtual cells and desk sensors driven by the physics model."""

    def __init__(self, client, room, run, port, noise=0.02, seed=0):
        self.c, self.room, self.run, self.noise = client, room, run, noise
        self.rng = np.random.default_rng(seed)
        self.angles = np.zeros(room.n_cells)
        self.moves = 0
        self.t, self.cloud = None, 0.0
        self._done, self._lock = {}, threading.Lock()
        self.rx = Receiver(port, self._on_command)

    def setup(self):
        c, run = self.c, self.run
        self.rx.start()
        o = roles(run)
        readers = remote(o["ctl"]), remote(o["view"])
        env_acp = make_acp(c, f"{run}envacp", [([o["env"]], ALL), (readers[0], C | R | N | DISC), (readers[1], R | N | DISC)])
        c.post("", o["env"], {"m2m:ae": {"rn": f"{run}env", "api": "Npolagrid", "rr": True, "srv": ["3"],
                                         "poa": [self.rx.url("env")]}}, 2)
        for cnt in ("sun", "desks"):
            c.post(f"{run}env", o["env"], {"m2m:cnt": {"rn": cnt, "mni": 10, "acpi": [env_acp]}}, 3)

        def cell(i):
            orig, rn, nu = f"C{run}p{i}", f"{run}p{i}", self.rx.url(f"p{i}")
            # ponytail: one ACP per cell (n ACPs per zone); the controller may also create under a cell's state
            acp = make_acp(c, f"{rn}acp", [([orig], ALL), (readers[0], C | R | N | DISC), (readers[1], R | N | DISC)])
            c.post("", orig, {"m2m:ae": {"rn": rn, "api": "Npolagrid", "rr": True, "srv": ["3"], "poa": [nu]}}, 2)
            c.post(rn, orig, {"m2m:cnt": {"rn": "command", "mni": 10, "acpi": [acp], "lbl": [f"polagrid/{run}/command"]}}, 3)
            c.post(rn, orig, {"cod:opeLl": {"rn": "state", "cnd": OPEN_LEVEL, "opeLl": 100, "minLl": 0, "maxLl": 100,
                                            "acpi": [acp], "lbl": [f"polagrid/{run}/state"]}}, 28)
            c.post(f"{rn}/command", orig, {"m2m:sub": {"rn": "s", "nu": [nu], "enc": {"net": [3]}, "nct": 1}}, 23)

        with ThreadPoolExecutor(20) as ex:
            list(ex.map(cell, range(self.room.n_cells)))

    def set_environment(self, t, cloud=0.0):
        """Move the simulated clock and publish the sun reading."""
        self.t, self.cloud = t, cloud
        alt, az = sun_position(t, self.room.lat, self.room.lon)
        self.c.create(f"{self.run}env/sun", f"C{self.run}env",
                      {"t": t.isoformat(), "alt": round(alt, 2), "az": round(az, 2),
                       "outdoor": round(window_lux(self.room, t, cloud))})

    def _on_command(self, path, con):
        i = int(path[1:])
        new = float(con["angles"][i])
        if abs(new - self.angles[i]) > 0.05:         # state only changes when the cell moves
            self.moves += abs(new - self.angles[i]) > MOVE_DEG
            self.angles[i] = new
            self.c.put(f"{self.run}p{i}/state", f"C{self.run}p{i}",
                       {"cod:opeLl": {"opeLl": round(100 * math.cos(math.radians(new)) ** 2)}})
        with self._lock:
            done = self._done.setdefault(con["cmd"], set())
            done.add(i)
            complete = len(done) == self.room.n_cells
        if complete:
            lux = simulate(self.room, self.t, self.angles, self.cloud, self.noise, self.rng)["desk_lux"]
            self.c.create(f"{self.run}env/desks", f"C{self.run}env",
                          {"cmd": con["cmd"], "lux": [round(float(v), 1) for v in lux]})


class Controller:
    """The MEC app: reads the sun, commands the cell group, reads desk lux. Uses the CSE only."""

    def __init__(self, client, run, port):
        self.c, self.run = client, run
        self.me = roles(run)["ctl"]
        self.seq = 0
        self.latencies = []                          # seconds from command POST to desk reading
        self._waiting = {}
        self.rx = Receiver(port, self._on_desks)

    def setup(self, n_cells):
        c, run = self.c, self.run
        self.rx.start()
        grant_discovery(c)
        acp = make_acp(c, f"{run}ctlacp", [(remote(self.me), ALL)])
        c.post("", self.me, {"m2m:ae": {"rn": f"{run}ctl", "api": "Npolagrid", "rr": True, "srv": ["3"],
                                        "poa": [self.rx.url("ctl")]}}, 2)
        mid = c.discover(self.me, lbl=f"polagrid/{run}/command", ty=3)   # the zone's cells, found by label
        if len(mid) != n_cells:
            raise RuntimeError(f"discovered {len(mid)} command containers, expected {n_cells}")
        c.post(f"{run}ctl", self.me, {"m2m:grp": {"rn": "grp", "mt": 3, "mnm": n_cells, "acpi": [acp], "mid": mid}}, 9)
        c.post(f"{run}env/desks", self.me, {"m2m:sub": {"rn": "ctl", "nu": [self.rx.url("ctl")],
                                                        "enc": {"net": [3]}, "nct": 1}}, 23)

    def sun(self):
        return self.c.latest(f"{self.run}env/sun", self.me)

    def command(self, angles):
        """Send one angle table to every cell; return the desk reading taken after all cells applied it."""
        self.seq += 1
        cmd = f"{self.run}c{self.seq}"
        slot = self._waiting[cmd] = [threading.Event(), None]
        t0 = time.perf_counter()
        self.c.create(f"{self.run}ctl/grp/fopt", self.me, {"cmd": cmd, "angles": [round(float(a), 1) for a in angles]})
        if not slot[0].wait(WAIT_S):
            raise TimeoutError(f"no desk reading for {cmd} within {WAIT_S}s")
        self.latencies.append(time.perf_counter() - t0)
        del self._waiting[cmd]
        return {"desk_lux": np.array(slot[1])}

    def _on_desks(self, path, con):
        slot = self._waiting.get(con["cmd"])
        if slot:
            slot[1] = con["lux"]
            slot[0].set()
