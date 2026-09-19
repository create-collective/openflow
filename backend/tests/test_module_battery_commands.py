"""A module's battery is read with whichever command it answers (SCRUM-99).

MOD_GET_PRECISE_BATTERY is unanswered on module firmware 2.1.2 -- measured at 1.09 s of timeout
per half per tick, with no reading to show for it, while MOD_GET_BATTERY answered the same
module in 0.22 s. Only the precise command was ported into DeviceService; nayactl's CLI has
carried the fallback all along, which is why it reads these modules and we did not.

Deliberately NOT a copy of the CLI's shape. nayactl samples five times in a row because it is
one-shot with no history; `_fold` here already takes a rolling median over the last five TICKS,
one reading each. Five reads per tick would repeat that work and add seconds to a six-second
loop.

The point of the cache is that a dead command is never sent twice. Without it, a module that
does not implement PRECISE costs a full timeout on every tick forever.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend._vendor.nayactl import constants as C  # noqa: E402
from openflow_backend.device.service import DeviceService  # noqa: E402

# Real payloads, captured from hardware.
LEGACY_REAL = bytes.fromhex("009c47a93b")    # donor Tune, fw 2.1.2
PRECISE_REAL = bytes.fromhex("1038")         # 4152 mV, the value nayactl documents

KEY = ("B269FA744772B9E1", 64)


class FakeTransport:
    """Answers only the commands a given module firmware implements, and counts the asking."""

    def __init__(self, answers):
        self.answers = answers
        self.sent = []

    def send_command(self, dest, cat, sub, payload=b"", timeout=None):
        self.sent.append(sub)
        got = self.answers.get(sub)
        return [type("R", (), {"valid": True, "payload": got})()] if got is not None else []


def svc():
    return DeviceService.__new__(DeviceService)


def new(answers):
    s = svc()
    s._module_batt = {}
    return s, FakeTransport(answers)


# --- decoding ----------------------------------------------------------------------------------

def test_the_two_payload_shapes_decode_to_the_same_kind_of_answer():
    """Different layouts and different units, both to millivolts. _to_millivolts sniffs the unit
    by magnitude, so neither needs a firmware-version check."""
    assert DeviceService._decode_precise(PRECISE_REAL) == 4152
    assert DeviceService._decode_legacy(LEGACY_REAL) == 4000


def test_a_module_saying_its_reading_is_invalid_is_believed():
    assert DeviceService._decode_precise(bytes.fromhex("103801")) is None


def test_nothing_is_invented_from_an_absent_or_empty_answer():
    for bad in (None, b"", b"\x00", bytes.fromhex("000000")):
        assert DeviceService._decode_precise(bad) is None
    for bad in (None, b"", b"\x00\x00"):
        assert DeviceService._decode_legacy(bad) is None


# --- choosing the command ------------------------------------------------------------------------

def test_new_firmware_answers_the_precise_command_and_is_remembered():
    s, t = new({C.MOD_GET_PRECISE_BATTERY: PRECISE_REAL})
    assert s._module_voltage(t, 0, KEY) == 4152
    assert s._module_batt[KEY] == "precise"
    assert t.sent == [C.MOD_GET_PRECISE_BATTERY], "the fallback must not be asked needlessly"


def test_older_firmware_falls_through_to_the_legacy_command():
    """The reported case: 2.1.2 does not implement the precise command at all."""
    s, t = new({C.MOD_GET_BATTERY: LEGACY_REAL})
    assert s._module_voltage(t, 0, KEY) == 4000
    assert s._module_batt[KEY] == "legacy"


def test_the_dead_command_is_never_asked_twice():
    """The whole point. Asking it every tick costs a timeout per half, forever, for nothing."""
    s, t = new({C.MOD_GET_BATTERY: LEGACY_REAL})
    for _ in range(5):
        s._module_voltage(t, 0, KEY)
    assert t.sent.count(C.MOD_GET_PRECISE_BATTERY) == 1, "probed once at docking, then never again"
    assert t.sent.count(C.MOD_GET_BATTERY) == 5


def test_a_module_answering_neither_is_not_pinned():
    """A module charging from flat can start answering later. Remembering 'neither' would mean
    never asking again, which is the one failure this cache must not create."""
    s, t = new({})
    assert s._module_voltage(t, 0, KEY) is None
    assert KEY not in s._module_batt
    s.answers = None
    t.answers = {C.MOD_GET_BATTERY: LEGACY_REAL}
    assert s._module_voltage(t, 0, KEY) == 4000, "it must still be willing to ask"


def test_two_modules_of_the_same_type_on_different_boards_are_tracked_apart():
    """Same key shape as the firmware cache (SCRUM-98): the half's serial, not the bay."""
    s, t = new({C.MOD_GET_BATTERY: LEGACY_REAL})
    other = ("42A44FE4776195CB", 64)
    s._module_voltage(t, 0, KEY)
    assert other not in s._module_batt


# --- the deep read path ---------------------------------------------------------------------
# This exists because a NameError in _query_half reached hardware: the method sees only a
# transport, so `dev` is not in scope there, and the battery cache key had to be passed in.
# The whole suite passed anyway -- nothing exercised this path at all -- and the first sign
# was a 500 from /api/status. One test that calls it would have caught it in a second.

class HalfTransport(FakeTransport):
    """Enough of a half to get through _query_half: a docked module and nothing else."""

    def send_command(self, dest, cat, sub, payload=b"", timeout=None):
        if cat == C.CAT_MODULE and sub == C.MOD_DETECT:
            return [type("R", (), {"valid": True, "payload": b"\x01"})()]
        if cat == C.CAT_MODULE and sub == C.MOD_SEND_HANDSHAKE:
            return [type("R", (), {"valid": True, "payload": b"\x00\x40"})()]   # left Tune
        return super().send_command(dest, cat, sub, payload, timeout)


def test_the_deep_read_reports_a_module_battery_on_older_firmware():
    """The reported case, through the method the Devices page actually calls."""
    s = svc()
    s._module_batt = {}
    t = HalfTransport({C.MOD_GET_BATTERY: LEGACY_REAL})
    got = s._query_half(t, 0, deep=False, owner="B269FA744772B9E1")
    module = got.get("module") or {}
    assert module.get("batteryMillivolts") == 4000
    assert module.get("batteryPercent") is not None


def test_the_deep_read_shares_the_cache_with_the_poll():
    """Both paths key on the half, so whichever asks first spares the other the dead command."""
    s = svc()
    s._module_batt = {}
    t = HalfTransport({C.MOD_GET_BATTERY: LEGACY_REAL})
    s._query_half(t, 0, deep=False, owner="B269FA744772B9E1")
    assert s._module_batt[("B269FA744772B9E1", 0x40)] == "legacy"
    before = t.sent.count(C.MOD_GET_PRECISE_BATTERY)
    s._query_half(t, 0, deep=False, owner="B269FA744772B9E1")
    assert t.sent.count(C.MOD_GET_PRECISE_BATTERY) == before, "the dead command must not return"
