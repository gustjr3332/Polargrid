"""Needs a running tinyIoT MN and runs inside WSL (the CSE calls back into this process):
    POLAGRID_CSE=http://127.0.0.1:3001/TinyIoT-mn001 python3 -m pytest tests/test_closed_loop.py
"""
import os
from datetime import datetime

import numpy as np
import pytest

from polagrid.onem2m import Client
from polagrid.physics import KST, Room, simulate
from polagrid.closed_loop import check_acp
from polagrid.zone import Controller, Zone

CSE = os.environ.get("POLAGRID_CSE")
pytestmark = pytest.mark.skipif(not CSE, reason="POLAGRID_CSE not set")


@pytest.fixture(scope="module")
def loop():
    host, cse = CSE.rsplit("/", 1)
    run = f"t{int(datetime.now().timestamp()) % 100000}"
    room = Room(rows=2, cols=3)
    client = Client(host, cse)
    zone, ctl = Zone(client, room, run, 9600, noise=0), Controller(client, run, 9601)
    zone.setup()
    ctl.setup(room.n_cells)
    yield room, zone, ctl
    zone.rx.stop()
    ctl.rx.stop()


def test_command_reaches_every_cell_and_desk_reading_comes_back(loop):
    room, zone, ctl = loop
    t = datetime(2026, 11, 5, 13, tzinfo=KST)
    zone.set_environment(t)
    assert ctl.sun()["outdoor"] > 20_000
    for angles in (np.zeros(6), np.full(6, 90.0), np.array([0, 30, 60, 90, 45, 15.0])):
        reading = ctl.command(angles)
        assert np.allclose(zone.angles, angles, atol=0.1)
        assert np.allclose(reading["desk_lux"], simulate(room, t, angles)["desk_lux"], atol=0.1)
    assert max(ctl.latencies) < 5


def test_each_role_gets_only_its_rights(loop):
    _, zone, _ = loop
    check_acp(zone.c, zone.run, zone.room.n_cells)
