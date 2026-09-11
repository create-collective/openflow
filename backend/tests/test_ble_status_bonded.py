"""The first BLE status capture with a host bonded, 2026-09-11, and what it pins.

The owner paired the PC over Bluetooth (slot 1), plugged the cable back in, and the left half
answered with slot 1's flags byte at 0x7f where every earlier capture had 0x08 on the active
slot and 0x00 elsewhere, and header byte 6 at 0x06 where it had always been 0x04. Peer address
4C:82:A9:7F:44:24, security level 2, 7.5 ms interval, 4 s timeout. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))
sys.path.insert(0, str(_BACKEND / "tests"))

from openflow_backend.device import ble_status as B     # noqa: E402
import test_ble_status as TB                              # noqa: E402

_REPO = next(p for p in _BACKEND.parents if (p / "device").is_dir())
BONDED = _REPO / "device" / "out" / "ble-status-paired-20260911.txt"


def _bonded():
    if not BONDED.exists():
        pytest.skip("the bonded capture is not on disk")
    return B.decode(BONDED.read_text(encoding="utf-8").strip())


def test_the_bonded_slot_lights_every_bit_and_names_its_host():
    d = _bonded()
    assert d["activeProfile"] == 1
    s = d["profiles"][1]
    assert s["flags"] == {"configured": True, "bonded": True, "connected": True, "active": True,
                          "hasPeerAddr": True, "encrypted": True, "authenticated": True}
    assert s["bonded"] and s["connected"] and s["isActive"]
    assert s["securityLevel"] == 2
    assert s["peerAddress"] == "4C:82:A9:7F:44:24"
    for other in (0, 2, 3, 4):
        assert d["profiles"][other]["flags"] == {k: False for k in B.PROFILE_FLAG_BITS}
        assert d["profiles"][other]["peerAddress"] is None


def test_the_header_says_a_host_is_connected_only_with_a_bond():
    d = _bonded()
    assert d["hostConnected"] is True and d["localAddrValid"] is True and d["advertising"] is False
    seen_unbonded = False
    for name, raw in TB._captured_blobs():
        e = B.decode(raw)
        assert e["localAddrValid"] is True, name
        bonded = any(p["bonded"] for p in e["profiles"])
        # hostConnected is set exactly on the captures that carry a bond (the 2026-09-11 full
        # read is one), never on the unbonded ones.
        assert e["hostConnected"] is bonded, name
        seen_unbonded = seen_unbonded or not bonded
    assert seen_unbonded, "no unbonded capture on disk to contrast against"


def test_an_active_unbonded_slot_has_only_the_active_bit():
    """On every capture without a bond, the active slot reads 0x08 and nothing else."""
    checked = 0
    for name, raw in TB._captured_blobs():
        e = B.decode(raw)
        if e["hostConnected"]:
            continue                       # a bonded capture; the test above covers it
        act = e["profiles"][e["activeProfile"]]
        assert act["flags"] == {**{k: False for k in B.PROFILE_FLAG_BITS}, "active": True}, name
        assert not act["bonded"] and not act["connected"] and act["peerAddress"] is None
        checked += 1
    assert checked > 0


def test_everything_else_in_the_bonded_capture_matches_the_board_we_know():
    d = _bonded()
    assert d["localAddress"] == "C5:F4:36:95:3D:3B"
    assert d["splitLink"]["peerAddress"] == "F3:69:F2:DE:F6:9C"
    assert d["profileCount"] == 5
