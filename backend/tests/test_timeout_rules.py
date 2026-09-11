"""The firmware's floor for the three timeouts, measured 2026-09-11, enforced before the wire.

Writing a 10 s idle timeout over USB was acked with flag 0xEA and the board kept 90 s; 30 s
was acked with 0x00 and stored. 0 is accepted as off for idle and sleep. Idle 400 s over a
300 s sleep was stored, so there is no ordering rule. No code read that flag before, so a slider
at 10 s would have flashed "successfully" and changed nothing. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import settings as SDB          # noqa: E402
from openflow_backend.device import flash as F           # noqa: E402
from openflow_backend.device import remap as R           # noqa: E402


@pytest.mark.parametrize("idle, sleep, batt", [
    (30000, 300000, 30000), (45000, 300000, 30000), (400000, 300000, 30000),
    (0, 300000, 30000), (90000, 0, 30000), (90000, 300000, 45000),
])
def test_what_the_board_stored_is_accepted(idle, sleep, batt):
    assert len(R.encode_timeouts(idle, sleep, batt)) == 12


@pytest.mark.parametrize("idle, sleep, batt, word", [
    (10000, 300000, 30000, "idle"), (29000, 300000, 30000, "idle"),
    (90000, 20000, 30000, "sleep"), (90000, 300000, 15000, "battery"),
    (90000, 300000, 5000, "battery"), (90000, 300000, 0, "battery"),
])
def test_what_the_board_refused_is_refused_here_first(idle, sleep, batt, word):
    with pytest.raises(R.RemapEncodeError, match=word):
        R.encode_timeouts(idle, sleep, batt)


def test_the_flash_names_a_firmware_rejection():
    """An ack with flag 0xEA is the firmware saying no to the value; the abort should say so
    rather than 'bad or missing ack'."""
    class Resp:
        valid = True
        def __init__(self, flags): self.flags, self.payload = flags, b""
    class T:
        def _send_raw(self, frame, timeout): return [Resp(R.ACK_REJECTED)]
    op = F.WriteOp(F.SYS_SET_TIMEOUTS, R.encode_timeouts(30000, 300000, 30000), "timeouts", cat=F.CAT_SYSTEM)
    res = F._apply([op], [("timeouts", [b"frame"])], T(), F.DesiredState(), reader=None)
    assert res["status"] == "aborted" and "rejected by the firmware" in res["reason"]
    assert res["ack_flags"] == 0xEA


def test_the_slider_refuses_the_dead_band_and_explains(monkeypatch):
    """1-29 s can never be stored; the settings writer says so instead of saving a value the
    keyboard will ignore. 0 and 30 stay fine."""
    wrote = []
    class Conn:
        def execute(self, sql, params=()): wrote.append(sql); return self
        def fetchone(self): return None
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr(SDB, "connect", lambda: Conn())
    with pytest.raises(ValueError, match="refuses values under 30"):
        SDB.set_setting("idle_timeout_s", 10)
    assert not wrote
    assert SDB.set_setting("idle_timeout_s", 0)["ok"]
    assert SDB.set_setting("idle_timeout_s", 30)["ok"]
    with pytest.raises(ValueError, match="refuses values under 30"):
        SDB.set_setting("sleep_timeout_s", 29)
