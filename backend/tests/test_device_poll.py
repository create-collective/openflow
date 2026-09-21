"""The live status tick: what NayaCore's 6 s poll does, done in OpenFlow's backend.

One light query per half per tick -- keyboard battery, module presence, module battery -- under
the service lock, with identity read once per port and battery folded across ticks. A half that
stops answering, or leaves the USB bus, is marked disconnected and its handle dropped. The
stream's signature ignores timestamps so an unchanged tick sends nothing. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import sse                      # noqa: E402
from openflow_backend.device import service as S          # noqa: E402

C = S.C
KB_MV = 4152          # 4.152 V, a full keyboard, as SYS_GET_KB_BATTERY_LEVEL reports it
MOD_MV = 4136         # the Tune this morning


class _Resp:
    valid = True

    def __init__(self, payload):
        self.payload = bytes(payload)


class FakeTransport:
    answers: dict = {}
    fail_all = False

    def __init__(self, port, dest):
        self.port, self.connected, self.sent = port, False, []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    @property
    def is_connected(self):
        return self.connected

    def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
        if FakeTransport.fail_all:
            raise S.TransportError(f"Write to {self.port} failed: gone")
        self.sent.append((category, subcmd))
        ans = FakeTransport.answers.get((category, subcmd))
        return [_Resp(ans)] if ans is not None else []


class Dev:
    def __init__(self, side, port):
        self.side, self.port, self.pid = side, port, 100 if side == "left" else 200
        self.description, self.serial_number = f"Create {side.title()}", "SN" + side


def _answers(kb_mv=KB_MV, module=True, mod_mv=MOD_MV):
    a = {
        (C.CAT_SYSTEM, C.SYS_GET_FW_VERSION): b"\x03\x29\x00",
        (C.CAT_SYSTEM, C.SYS_GET_HW_ID_NUMBER): b"HWID-1",
        (C.CAT_BLE, C.BLE_GET_ADDRESS): bytes.fromhex("C5F436953D3B"),
        (C.CAT_SYSTEM, C.SYS_GET_KB_BATTERY_LEVEL): kb_mv.to_bytes(2, "big"),
        (C.CAT_MODULE, C.MOD_DETECT): b"\x01" if module else b"\x00",
        (C.CAT_MODULE, C.MOD_SEND_HANDSHAKE): b"\x01\x11",          # address 0x11: a Touch, right
        (C.CAT_MODULE, C.MOD_GET_PRECISE_BATTERY): mod_mv.to_bytes(2, "big") + b"\x00",
    }
    return a


@pytest.fixture
def svc(monkeypatch):
    FakeTransport.answers = _answers()
    FakeTransport.fail_all = False
    monkeypatch.setattr(S, "SerialTransport", FakeTransport)
    monkeypatch.setattr(S, "find_naya_serial_ports", lambda: [Dev("left", "COM9"), Dev("right", "COM10")])
    return S.DeviceService()


def test_a_tick_reports_battery_and_the_docked_module(svc):
    snap = svc.tick_all()
    left = next(h for h in snap["halves"] if h["side"] == "left")
    assert left["connected"] is True
    assert left["batteryMillivolts"] == KB_MV and 0 <= left["batteryPercent"] <= 100
    assert left["firmwareVersion"] and left["hardwareId"] == "HWID-1"
    assert left["bleAddress"] == "C5:F4:36:95:3D:3B"
    assert left["module"]["type"] == "Touch" and left["module"]["batteryMillivolts"] == MOD_MV
    assert left["at"]


def test_identity_is_read_once_per_port_and_battery_every_tick(svc):
    svc.tick_all(); svc.tick_all(); svc.tick_all()
    t = svc._transports["COM9"]
    assert sum(1 for c in t.sent if c == (C.CAT_SYSTEM, C.SYS_GET_FW_VERSION)) == 1
    assert sum(1 for c in t.sent if c == (C.CAT_SYSTEM, C.SYS_GET_KB_BATTERY_LEVEL)) == 3


def test_a_firmware_flash_is_the_one_thing_that_makes_that_cache_a_lie(svc):
    """After an update the half is still connected, on the same port, running a different
    version. forget_identity() is how the next tick learns that (SCRUM-102/104)."""
    before = next(h for h in svc.tick_all()["halves"] if h["side"] == "left")["firmwareVersion"]
    FakeTransport.answers[(C.CAT_SYSTEM, C.SYS_GET_FW_VERSION)] = b"\x03\x23\x04"
    unchanged = next(h for h in svc.tick_all()["halves"] if h["side"] == "left")["firmwareVersion"]
    assert unchanged == before, "an ordinary tick keeps the cached identity, as it should"

    svc.forget_identity()
    after = next(h for h in svc.tick_all()["halves"] if h["side"] == "left")["firmwareVersion"]
    assert after != before, "the version on screen would still be the pre-flash one"


def test_battery_is_a_rolling_median_across_ticks(svc):
    """One noisy reading does not move the number; nayactl takes five samples per read for
    the same reason."""
    svc.tick_all()
    FakeTransport.answers[(C.CAT_SYSTEM, C.SYS_GET_KB_BATTERY_LEVEL)] = (3000).to_bytes(2, "big")
    snap = svc.tick_all()
    left = next(h for h in snap["halves"] if h["side"] == "left")
    assert left["batteryMillivolts"] == KB_MV, "the median of (4152, 3000) is the higher one"


def test_a_half_that_answers_with_nothing_says_so_and_can_come_back(svc):
    """The hollow port (SCRUM-107): every reply is an empty frame.

    It is what a half looks like while its partner is on different firmware, and the half is
    fine -- it types normally. Two things were wrong. The empty identity was cached like any
    other, and `.get(port)` cannot tell "cached nothing" from "never read", so the half stayed
    blank for as long as it was plugged in, including after it had started answering again. And
    nothing said the state was happening at all, so the page drew a card of empty fields, which
    reads as a dead half.
    """
    FakeTransport.answers = {}
    snap = svc.tick_all()
    left = next(h for h in snap["halves"] if h["side"] == "left")
    assert left["connected"] is True, "the port opened and took every command"
    assert left["reporting"] is False
    assert left.get("firmwareVersion") is None

    FakeTransport.answers = _answers()
    back = next(h for h in svc.tick_all()["halves"] if h["side"] == "left")
    assert back["firmwareVersion"], "an empty read must not be remembered as the answer"
    assert "reporting" not in back


def test_a_half_that_leaves_the_bus_is_marked_gone_and_its_handle_dropped(svc, monkeypatch):
    svc.tick_all()
    monkeypatch.setattr(S, "find_naya_serial_ports", lambda: [Dev("left", "COM9")])
    snap = svc.tick_all()
    right = next(h for h in snap["halves"] if h["side"] == "right")
    assert right["connected"] is False and "USB" in right["error"]
    assert "COM10" not in svc._transports


def test_a_half_that_stops_answering_is_marked_disconnected(svc):
    svc.tick_all()
    FakeTransport.fail_all = True
    snap = svc.tick_all()
    assert all(h["connected"] is False for h in snap["halves"])
    assert svc._transports == {}


def test_no_module_means_no_module(svc):
    FakeTransport.answers = _answers(module=False)
    snap = svc.tick_all()
    assert all(h["module"] is None for h in snap["halves"])


def test_the_stream_signature_ignores_timestamps():
    devs = [{"port": "COM9", "side": "left"}]
    a = {"halves": [{"side": "left", "connected": True, "batteryPercent": 90, "at": "t1"}]}
    b = {"halves": [{"side": "left", "connected": True, "batteryPercent": 90, "at": "t2"}]}
    c = {"halves": [{"side": "left", "connected": True, "batteryPercent": 89, "at": "t3"}]}
    sa, pa = sse.compose(devs, a)
    sb, _ = sse.compose(devs, b)
    sc, _ = sse.compose(devs, c)
    assert sa == sb and sa != sc
    assert pa["status"]["halves"][0]["at"] == "t1", "the payload keeps the timestamp"
