"""A key's four behaviours live in TWO records, 0x52 apart.

Captured live 2026-09-03: NayaFlow, asked for a double-tap and a tap+hold, wrote

    pos 0x49  type 0x10  tap B / hold Z      (primary bank)
    pos 0x9b  type 0x10  tap X / hold Y      (secondary bank, 0x49 + 0x52)

and pressing that key produced b / zzz / x / yyy for tap / hold / double-tap / tap+hold. So the
secondary bank's tap slot IS double-tap and its hold slot IS tap+hold.

Before this, decode_keymap dropped everything above MAX_POSITION, so every double-tap and
tap+hold binding on the board was silently discarded on read -- including one at pos 0x87 that
had been sitting on the reference device since a much older flash.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr  # noqa: E402

# The exact WRITE_LAYER_DATA payload NayaFlow sent (device/out/doubletap.pcap).
CAPTURED = ("00491018c80003010100c8001d0007000000000005000700000000"
            "009b1018c80003010100c8001c000700000000001b00070000000000")


def test_split_position():
    assert kr.split_position(0x49) == (0x49, False)
    assert kr.split_position(0x9B) == (0x49, True), "0x9b must fold onto key 0x49"
    assert kr.split_position(0x87) == (0x35, True)
    assert kr.SECOND_BANK == 0x52, "the offset is the span of the primary bank"
    print("  0x9b -> key 0x49 secondary, 0x87 -> key 0x35 secondary")


def test_four_behaviours_decode_onto_one_key():
    recs = list(kr.parse_records(bytes.fromhex(CAPTURED)[1:]))
    assert {p for p, _, _ in recs} == {0x49, 0x9B}, "expected the two banks of one key"
    decoded = kr.decode_keymap({"layers": {0: recs}, "led": {}}, {})
    slots = dict((b, c) for b, _at, c in decoded[0][0x49])
    assert slots == {"press": "B", "hold": "Z", "double_tap": "X", "tap_hold": "Y"}, slots
    assert not decoded["_dropped"], f"nothing should be dropped now: {decoded['_dropped']}"
    print(f"  key 0x49 decodes to all four: {slots}")


def test_secondary_bank_is_no_longer_dropped():
    """The regression this fixes: a lone secondary record used to vanish entirely."""
    recs = [(0x9B, 0x10, bytes.fromhex("c80003010100c8001c000700000000001b00070000000000"))]
    decoded = kr.decode_keymap({"layers": {0: recs}, "led": {}}, {})
    assert 0x49 in decoded[0], "a secondary-bank record did not reach its key"
    assert not decoded["_dropped"]
    print("  a lone secondary record lands on its key instead of being dropped")


if __name__ == "__main__":
    for fn in (test_split_position,
               test_four_behaviours_decode_onto_one_key,
               test_secondary_bank_is_no_longer_dropped):
        print(fn.__name__)
        fn()
    print("\nOK")
