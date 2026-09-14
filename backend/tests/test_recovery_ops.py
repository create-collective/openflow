"""Recovery/troubleshooting procedures: the frames are pinned, and every op is gated off.

These are destructive device writes wired ahead of a donor unit. The point of the tests is to catch
a wrong opcode or payload BEFORE anything is ever enabled -- the frame bytes are asserted against
the values recovered from NayaCore v6.11.0 (opcodes) and its validation strings (payload shapes).
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import recovery_ops as ro          # noqa: E402
from openflow_backend.device.commands import CommandError       # noqa: E402


# The exact frame each op must produce -- (cat, sub, payload hex). A regression here is a wrong
# byte heading for a keyboard, so it is asserted literally.
EXPECT = {
    "reset_normal":              (0xEE, 0x10CE, ""),
    "reset_mcuboot":             (0xEE, 0x10AE, ""),
    "reset_dfu":                 (0xEE, 0x10BE, ""),
    "reset_module":              (0xDE, 0x1006, ""),
    "set_host_os":               (0xFE, 0x1005, "01"),   # with os=mac
    "module_battery_recovery":   (0xFE, 0x1003, ""),
    "ble_set_pair_address":      (0xBE, 0x1001, "e2f79ee87c18"),
    "ble_unpair_address":        (0xBE, 0x1003, "e2f79ee87c18"),
    "ble_unpair_all":            (0xBE, 0x1004, ""),
    "ble_clear_all_split_links": (0xBE, 0x1010, ""),
    "clear_all_data":            (0x30, 0x10CA, ""),
    "format_partition":          (0xFA, 0x1002, "01"),   # with partition=1
    "erase_chip":                (0xFA, 0x1006, ""),
}
ARGS = {"set_host_os": {"os": "mac"}, "format_partition": {"partition": 1},
        "ble_set_pair_address": {"mac": "E2:F7:9E:E8:7C:18"},
        "ble_unpair_address": {"mac": "E2:F7:9E:E8:7C:18"}}


def test_every_op_builds_exactly_the_expected_frame():
    for op_id, (cat, sub, pay) in EXPECT.items():
        got = ro.frame_for(op_id, ARGS.get(op_id, {}))
        assert got == (cat, sub, bytes.fromhex(pay)), f"{op_id}: {got}"


def test_the_registry_and_the_expectations_cover_the_same_ops():
    assert set(ro.BY_ID) == set(EXPECT), "an op was added/removed without pinning its frame"


def test_every_op_ships_disabled():
    assert all(not o.enabled for o in ro.REGISTRY), "a recovery op is enabled before a donor test"


def test_host_os_is_one_byte_under_two():
    assert ro.frame_for("set_host_os", {"os": "windows"})[2] == b"\x00"
    assert ro.frame_for("set_host_os", {"os": "mac"})[2] == b"\x01"
    with pytest.raises(ValueError):
        ro.frame_for("set_host_os", {"os": "linux"})    # NayaCore: value < 2


def test_a_pair_address_must_be_six_bytes():
    with pytest.raises(ValueError):
        ro.frame_for("ble_set_pair_address", {"mac": "12:34"})


def test_public_list_carries_confirm_text_and_never_leaks_a_frame():
    for o in ro.public_list():
        assert o["confirm"] and o["danger"] in ("reset", "recovery", "destructive")
        assert o["enabled"] is False
        assert "payload" not in o and "sub" not in o


# --- the gate: nothing runs, even with force, while disabled -------------------------------------- #

class _Svc:
    """Minimal stand-in exposing run_recovery_op via the real class, with a fake transport path."""
    pass


def _service(monkeypatch):
    from openflow_backend.device.service import DeviceService
    svc = DeviceService()
    sent = []

    class Dev:
        side, port = "left", "COM-TEST"

    class T:
        def send_command(self, dest, cat, sub, payload=b"", **k):
            sent.append((cat, sub, bytes(payload))); return []

    monkeypatch.setattr(svc, "_with_transport", lambda side, fn: fn(T(), 0x50, Dev()))
    return svc, sent


def test_a_disabled_op_refuses_even_with_force(monkeypatch):
    svc, sent = _service(monkeypatch)
    with pytest.raises(CommandError, match="disabled until"):
        svc.run_recovery_op("left", "erase_chip", force=True)
    assert sent == [], "a disabled op must send nothing"


def test_an_enabled_op_still_needs_force(monkeypatch):
    svc, sent = _service(monkeypatch)
    # frozen dataclass -> swap in a replace()d copy with enabled=True
    import dataclasses
    enabled = dataclasses.replace(ro.BY_ID["reset_normal"], enabled=True)
    monkeypatch.setitem(ro.BY_ID, "reset_normal", enabled)
    with pytest.raises(CommandError, match="confirmation"):
        svc.run_recovery_op("left", "reset_normal", force=False)
    assert sent == []


def test_an_enabled_forced_op_sends_the_right_frame(monkeypatch):
    svc, sent = _service(monkeypatch)
    import dataclasses
    monkeypatch.setitem(ro.BY_ID, "reset_normal", dataclasses.replace(ro.BY_ID["reset_normal"], enabled=True))
    svc.run_recovery_op("left", "reset_normal", force=True)
    assert sent == [(0xEE, 0x10CE, b"")]
