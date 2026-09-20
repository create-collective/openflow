"""Every 0xED payload starts with a target byte, and a short one is zero-filled -- not rejected.

THE BUG. `service.led` sent `LED_ADJUST_BRIGHTNESS` and `LED_SELECT_EFFECT` as a bare `[value]`.
The device reads a 0xED payload positionally as `[target] + [data...]`, so those became
target=<value>, data=0. Brightness was inert. Effect always selected effect 0. Both ack'd
normally, which is why neither was noticed: on this command family a well-formed frame carrying
nonsense parameters answers exactly like a correct one, so `valid=True` proves the frame parsed
and nothing more.

MEASURED ON HARDWARE 2026-09-09 (left half, dest 0x50). No response distinguishes these, so a
human watched the board for each one:

    LED_ADJUST_BRIGHTNESS [10]       board OFF     target 10, level defaulted to 0
    LED_ADJUST_BRIGHTNESS [100]      board OFF     target 100, level defaulted to 0
    LED_ADJUST_BRIGHTNESS [0, 15]    board DIM
    LED_ADJUST_BRIGHTNESS [3, 100]   board FULL
    LED_ADJUST_BRIGHTNESS [200, 15]  board DIM     the target's VALUE is ignored
    LED_SELECT_EFFECT     [1]        SOLID         target 1, effect defaulted to 0
    LED_SELECT_EFFECT     [0, 1]     BREATHING
    LEDS_OFF              []         board OFF     sole parameter IS the target; zero-fills

The last line is why the one-parameter commands are correct as they stand and must not have a
byte added to them: an empty payload zero-fills to target 0 and works. The rule is the payload
LENGTH, not "always send a target".

The target's value being ignored is a finding about this firmware, not a licence to send
anything: it is pinned to 0 so a firmware that starts honouring it addresses the default.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from nayactl import constants as C                          # noqa: E402
from openflow_backend.device.service import DeviceService   # noqa: E402


class Recorder:
    """Records (dest, category, subcmd, payload) instead of talking to a board."""
    def __init__(self):
        self.sent = []
    def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
        self.sent.append((dest, category, subcmd, bytes(payload)))
        return []


@pytest.fixture
def svc(monkeypatch):
    s = DeviceService()
    rec = Recorder()

    class Dev:
        side, port = "left", "COM-TEST"

    monkeypatch.setattr(s, "_require_side", lambda side, serial=None: Dev())
    monkeypatch.setattr(s, "_transport_for", lambda port, dest: rec)
    s._recorder = rec
    return s


def only(svc):
    assert len(svc._recorder.sent) == 1, svc._recorder.sent
    return svc._recorder.sent[0]


def test_brightness_carries_the_target_byte_before_the_level(svc):
    """THE BUG: this was `bytes([value])`, which set the level to 0 on every call."""
    svc.led("left", "brightness", 40)
    dest, cat, sub, payload = only(svc)
    assert (cat, sub) == (C.CAT_LED, C.LED_ADJUST_BRIGHTNESS)
    assert payload == bytes([0, 40]), payload.hex()


def test_effect_carries_the_target_byte_before_the_index(svc):
    """Same shape: `[1]` selected effect 0 while looking like it asked for effect 1."""
    svc.led("left", "effect", 1)
    _, cat, sub, payload = only(svc)
    assert (cat, sub) == (C.CAT_LED, C.LED_SELECT_EFFECT)
    assert payload == bytes([0, 1]), payload.hex()


def test_the_level_is_never_alone_in_the_payload(svc):
    """The regression that matters: a one-byte payload is the broken form, whatever the value."""
    for value in (0, 1, 15, 100, 255):
        svc._recorder.sent.clear()
        svc.led("left", "brightness", value)
        _, _, _, payload = only(svc)
        assert len(payload) == 2, f"level {value} sent as {payload.hex()}"
        assert payload[1] == value & 0xFF


@pytest.mark.parametrize("action,sub", [
    ("on", C.LED_ON), ("off", C.LED_OFF), ("toggle", C.LED_TOGGLE),
    ("halt", C.LED_HALT), ("resume", C.LED_RESUME),
])
def test_the_one_parameter_commands_send_no_payload_at_all(svc, action, sub):
    """Their only parameter IS the target, and an empty payload zero-fills to 0. LEDS_OFF with
    no payload was confirmed to switch the board off on hardware, so adding a byte here would be
    changing something that works."""
    svc.led("left", action)
    _, cat, got_sub, payload = only(svc)
    assert (cat, got_sub) == (C.CAT_LED, sub)
    assert payload == b"", payload.hex()


def test_the_target_is_pinned_to_zero(svc):
    """Its value is ignored on the firmware measured, so it stays at the default rather than
    being left to a caller. A firmware that starts honouring it then addresses target 0."""
    assert DeviceService.LED_TARGET == 0
    svc.led("left", "brightness", 100)
    assert only(svc)[3][0] == 0


def test_a_missing_value_is_still_refused(svc):
    for action in ("brightness", "effect"):
        with pytest.raises(ValueError):
            svc.led("left", action)
