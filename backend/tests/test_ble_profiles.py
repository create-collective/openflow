"""The Bluetooth slots page: read the five slots, select one, clear one.

Wire form from NayaCore's own validation strings: "Invalid parameter size (%1) for
SEL/CLEAR_BLE_PROFILE, should be 1" and "Invalid profile (%1) ..., should be less than 5" --
one byte, the slot index, below 5. The status blob is the 2026-09-10 capture with slot 1 active
(the owner's BT_DEVICE_1 press), so the read side is checked against a real board. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))
sys.path.insert(0, str(_BACKEND / "tests"))

from openflow_backend.api import rest                       # noqa: E402
from openflow_backend.device import service as S            # noqa: E402
import test_ble_status as TB                                # noqa: E402

C = S.C
BLOB = dict(TB._captured_blobs()).get("after-a3-outputs-test-20260910.json")


class _Resp:
    valid = True

    def __init__(self, payload):
        self.payload = bytes(payload)


class FakeTransport:
    """Answers BLE_GET_STATUS with the captured blob; records every command."""
    def __init__(self, port, dest):
        self.connected, self.sent = False, []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    @property
    def is_connected(self):
        return self.connected

    def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
        self.sent.append((category, subcmd, bytes(payload)))
        if category == C.CAT_BLE and subcmd == C.BLE_GET_STATUS and BLOB:
            return [_Resp(bytes.fromhex(BLOB))]
        return []


class Dev:
    port, side = "COM9", "left"


@pytest.fixture
def svc(monkeypatch):
    if not BLOB:
        pytest.skip("the 2026-09-10 capture is not on disk")
    monkeypatch.setattr(S, "SerialTransport", FakeTransport)
    s = S.DeviceService()
    monkeypatch.setattr(s, "_require_side", lambda side: Dev())
    return s


def _sent(svc):
    return svc._transports["COM9"].sent


def test_the_slots_read_matches_the_board():
    """Five slots, slot 1 active after the owner's BT_DEVICE_1 press, nothing bonded, 0 reserved."""
    monkey = pytest.MonkeyPatch()
    try:
        if not BLOB:
            pytest.skip("capture missing")
        monkey.setattr(S, "SerialTransport", FakeTransport)
        s = S.DeviceService(); monkey.setattr(s, "_require_side", lambda side: Dev())
        out = s.ble_profiles("left")
        assert out["activeProfile"] == 1 and len(out["slots"]) == 5
        assert [x["active"] for x in out["slots"]] == [False, True, False, False, False]
        assert not any(x["bonded"] for x in out["slots"])
        assert out["slots"][0]["reserved"] and not any(x["reserved"] for x in out["slots"][1:])
        assert out["localAddress"] == "C5:F4:36:95:3D:3B"
    finally:
        monkey.undo()


def test_select_sends_one_byte_and_reads_back(svc):
    out = svc.select_ble_profile("left", 2)
    cmds = _sent(svc)
    assert cmds[0] == (C.CAT_BLE, C.BLE_SELECT_PROFILE, b"\x02")
    assert cmds[1][:2] == (C.CAT_BLE, C.BLE_GET_STATUS)
    # The fake board still says slot 1, so the service reports the disagreement honestly.
    assert out["requested"] == 2 and out["activeProfile"] == 1 and out["ok"] is False
    assert "different active slot" in out["note"]


def test_select_of_the_slot_the_board_reports_is_ok(svc):
    out = svc.select_ble_profile("left", 1)
    assert out["ok"] is True and out["note"] is None


@pytest.mark.parametrize("bad", [5, -1, 99, "2", 2.0, None, True])
def test_select_refuses_anything_but_a_slot_index(svc, bad):
    with pytest.raises(ValueError):
        svc.select_ble_profile("left", bad)
    assert "COM9" not in svc._transports, "nothing was sent"


def test_slot_zero_is_reserved_unless_overridden(svc):
    with pytest.raises(ValueError, match="reserved"):
        svc.select_ble_profile("left", 0)
    out = svc.select_ble_profile("left", 0, allow_reserved=True)
    assert _sent(svc)[0] == (C.CAT_BLE, C.BLE_SELECT_PROFILE, b"\x00")
    assert out["requested"] == 0


def test_clear_needs_force_and_sends_one_byte(svc):
    with pytest.raises(S.DangerousCommandError):
        svc.clear_ble_profile("left", 3)
    assert "COM9" not in svc._transports
    out = svc.clear_ble_profile("left", 3, force=True)
    assert _sent(svc)[0] == (C.CAT_BLE, C.BLE_CLEAR_PROFILE, b"\x03")
    assert out["cleared"] == 3 and out["bonded"] is False


def test_clear_never_touches_slot_zero(svc):
    with pytest.raises(ValueError, match="reserved"):
        svc.clear_ble_profile("left", 0, force=True)


# --- the routes' gates ---------------------------------------------------------------------

app = FastAPI()
app.include_router(rest.router)
client = TestClient(app)


def test_select_route_refuses_without_its_token():
    r = client.post("/rpc/select-ble-profile", json={"index": 2})
    assert r.status_code == 400 and "SELECT" in r.text
    for bad in ("select", "FLASH", "CLEAR", ""):
        assert client.post("/rpc/select-ble-profile", json={"index": 2, "confirm": bad}).status_code == 400


def test_clear_route_refuses_without_its_own_token():
    r = client.post("/rpc/clear-ble-profile", json={"index": 2, "confirm": "SELECT"})
    assert r.status_code == 400 and "CLEAR" in r.text
