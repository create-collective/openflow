"""Hold-tap records: two actions on one key, and a header that is parameters not constants.

Naya's changelog claims four behaviours per key. It is true, and the mechanism is TWO records
0x52 apart (see test_second_bank.py) -- each an ordinary hold-tap record holding two actions.

The header is `01 01 <flavour> <term u16 LE>` (the 0x10 OneKey form prefixes `<term u16> 03`).
Two captures taken a day apart prove both fields vary, which is why this file pins the header by
reproducing real captures at their own flavour/term rather than freezing a constant:

    2026-09-02 capture:  ...01 01 02 c2 00   flavour 2 (tap-preferred), term 194
    2026-09-03 capture:  ...01 01 00 c8 00   flavour 0 (hold-preferred), term 200

The flavour is the ZMK enum, valid range 0-3. Writing 4 was accepted, stored, and stopped every
key on the board until a power cycle -- so encode_hold_tap refuses out-of-range flavours.
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

_FIXTURE = json.loads((Path(__file__).with_name("hold-tap-fixture.json")).read_text())
RECORDS = {pos: (typ, param) for pos, typ, param in
           kr.parse_records(bytes.fromhex(_FIXTURE["write_layer_data_payload"])[1:])}

# The 2026-09-03 double-tap capture: primary and secondary bank of one key.
DOUBLETAP = ("00491018c80003010100c8001d0007000000000005000700000000"
             "009b1018c80003010100c8001c000700000000001b00070000000000")


def test_reproduces_the_2026_09_02_capture():
    """flavour 2 / term 194 -- NayaFlow's settings that day."""
    for pos, tap, hold in ((0x20, ("key", "A"), ("modifier", "LCTRL")),
                           (0x25, ("key", "DELETE"), ("key", "BACKSPACE")),
                           (0x35, ("key", "BACKSPACE"), ("modifier", "LCTRL"))):
        typ, want = RECORDS[pos]
        got = R.encode_hold_tap(tap, hold, typ, flavour=2, term=194)
        assert got == want, f"pos {pos:#04x} differs from the captured record"
    print("  3 records reproduced at flavour 2 / term 194 (incl. two ordinary keys on 0x25)")


def test_reproduces_the_2026_09_03_capture():
    """flavour 0 / term 200 -- a different day, different settings, same encoder."""
    for pos, tap, hold in ((0x49, ("key", "B"), ("key", "Z")),
                           (0x9B, ("key", "X"), ("key", "Y"))):
        typ, param = {p: (t, v) for p, t, v in kr.parse_records(bytes.fromhex(DOUBLETAP)[1:])}[pos]
        got = R.encode_hold_tap(tap, hold, typ, flavour=0, term=200)
        assert got == param, f"pos {pos:#04x} differs from the captured record"
    print("  both banks reproduced at flavour 0 / term 200")


def test_flavour_and_term_are_the_only_difference():
    """The two captures differ ONLY in those two fields -- that is what identifies them."""
    a = R.encode_hold_tap(("key", "B"), ("key", "Z"), R.HOLD_TAP_ONEKEY, flavour=2, term=194)
    b = R.encode_hold_tap(("key", "B"), ("key", "Z"), R.HOLD_TAP_ONEKEY, flavour=0, term=200)
    assert a[3:8] != b[3:8] and a[8:] == b[8:], "only the header should differ"
    assert a.hex().startswith("c20003010102c200") and b.hex().startswith("c80003010100c800")
    print("  header varies with flavour/term; the action slots are untouched")


def test_out_of_range_flavour_is_refused():
    """The value that stopped the keyboard. ZMK hold-tap flavours are 0-3."""
    for bad in (4, 5, 255, -1):
        try:
            R.encode_hold_tap(("key", "A"), ("key", "B"), flavour=bad)
        except R.RemapEncodeError:
            continue
        raise AssertionError(f"flavour {bad} was accepted")
    for ok in R.HOLD_TAP_FLAVOURS:
        R.encode_hold_tap(("key", "A"), ("key", "B"), flavour=ok)
    print(f"  flavours {list(R.HOLD_TAP_FLAVOURS)} accepted, out-of-range refused")


def test_two_different_keys_round_trip():
    typ, want = RECORDS[0x25]
    slots = kr.translate(typ, want, {})
    assert ("press", "key", "DELETE") in slots and ("hold", "key", "BACKSPACE") in slots
    print("  two distinct keys survive encode -> decode")


if __name__ == "__main__":
    for fn in (test_reproduces_the_2026_09_02_capture,
               test_reproduces_the_2026_09_03_capture,
               test_flavour_and_term_are_the_only_difference,
               test_out_of_range_flavour_is_refused,
               test_two_different_keys_round_trip):
        print(fn.__name__)
        fn()
    print("\nOK")
