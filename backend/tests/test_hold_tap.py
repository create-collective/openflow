"""Hold-tap records: two actions on one key.

Naya's changelog claims four behaviours per key and NayaFlow's editor cannot produce even
two, which left it unclear whether the firmware supported it at all. It does: the board
carries records NayaFlow itself flashed with two DIFFERENT keys on tap vs hold, and we wrote
one and pressed it (C4c: tap B / hold Z).

The headers are reproduced from those captured records rather than generated, because their
inner bytes are not fully understood -- and one of them is dangerous to guess at (see
docs/phase-c-test-plan.md: an out-of-range value stopped the whole keyboard until a power
cycle). These tests pin the encoder to the bytes the device is known to accept.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

# Layer 0 exactly as NayaFlow flashed it, read from a fixture rather than transcribed --
# hand-copying these records dropped a byte twice while these tests were being written.
_FIXTURE = json.loads((Path(__file__).with_name("hold-tap-fixture.json")).read_text())
RECORDS = {pos: (typ, param) for pos, typ, param in
           kr.parse_records(bytes.fromhex(_FIXTURE["write_layer_data_payload"])[1:])}


def test_encoder_reproduces_captured_records():
    cases = [(0x20, ("key", "A"), ("modifier", "LCTRL")),
             (0x25, ("key", "DELETE"), ("key", "BACKSPACE")),
             (0x35, ("key", "BACKSPACE"), ("modifier", "LCTRL"))]
    for pos, tap, hold in cases:
        typ, want = RECORDS[pos]
        got = R.encode_hold_tap(tap, hold, typ)
        assert got == want, f"pos {pos:#04x} re-encode differs from the captured record"
    print(f"  {len(cases)} captured hold-tap records re-encode byte-exactly")


def test_two_different_keys_round_trip():
    """0x25 is the proof this is not just modifier-on-hold: two ordinary keys."""
    typ, want = RECORDS[0x25]
    slots = kr.translate(typ, want, {})
    assert ("press", "key", "DELETE") in slots and ("hold", "key", "BACKSPACE") in slots
    ours = R.encode_hold_tap(("key", "B"), ("key", "Z"))
    assert kr.translate(R.HOLD_TAP_ONEKEY, ours, {}) == [("press", "key", "B"), ("hold", "key", "Z")]
    print("  two distinct keys survive encode -> decode (this is what we wrote and pressed)")


def test_headers_are_the_captured_constants():
    """The headers must stay verbatim. Byte 5 of the OneKey header is a validated field: the
    board accepted 0x04 there, stored it, and then stopped emitting ANY key until it was
    power-cycled. Nothing here should invent header bytes."""
    assert R.HOLD_TAP_HEADERS[R.HOLD_TAP_HOME].hex() == "010102c200"
    assert R.HOLD_TAP_HEADERS[R.HOLD_TAP_ONEKEY].hex() == "c20003010102c200"
    # the OneKey header is the home-row header with three bytes prepended
    assert R.HOLD_TAP_HEADERS[R.HOLD_TAP_ONEKEY].endswith(R.HOLD_TAP_HEADERS[R.HOLD_TAP_HOME])
    print("  headers unchanged; OneKey = 3 bytes + the home-row header")


def test_unknown_record_type_is_refused():
    try:
        R.encode_hold_tap(("key", "A"), ("key", "B"), 0x99)
    except R.RemapEncodeError:
        print("  an unknown hold-tap record type is refused")
        return
    raise AssertionError("an unknown record type was accepted")


if __name__ == "__main__":
    for fn in (test_encoder_reproduces_captured_records,
               test_two_different_keys_round_trip,
               test_headers_are_the_captured_constants,
               test_unknown_record_type_is_refused):
        print(fn.__name__)
        fn()
    print("\nOK")
