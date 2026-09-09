"""The outputs record (0x08, Wireless / USB-C switching) is WRITTEN, not just decoded.

It was held back as "pending a hardware check", and a flash of Naya's own System layer reported
four bindings it could not write -- BT_OUT and USB_DEVICE on keys 47/48 and 71/72 -- so the
user's Bluetooth-output keys silently kept whatever the board had. The check that matters for
writing was already in hand: NayaFlow put exactly these bytes on this board (2026-09-08, layer 2),
and its database names them at those positions. test_outputs_record.py pins the decode and the
evidence; this pins the encode and the round trip. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

# Read off the board on 2026-09-09 after NayaFlow's own flash (verify-probe-after-nayaflow.json),
# layer 2: the four positions the flash report named.
ON_BOARD = {0x2F: "02000000", 0x30: "01000000", 0x47: "02000000", 0x48: "01000000"}


def _rec(code):
    return F._binding_rows_to_record([{"beh": "press", "at": "out", "ac": code}], 200, 0, {})


def test_both_outputs_encode_to_the_vendor_bytes():
    assert _rec("BT_OUT") == (R.OUTPUTS, bytes.fromhex("02000000"))
    assert _rec("USB_DEVICE") == (R.OUTPUTS, bytes.fromhex("01000000"))
    print("  BT_OUT -> 08 02000000, USB_DEVICE -> 08 01000000")


def test_round_trip_through_the_decoder():
    for code in ("BT_OUT", "USB_DEVICE"):
        typ, param = _rec(code)
        assert kr.translate(typ, param, {}) == [("press", "out", code)]
    print("  encode -> decode returns the same action")


def test_matches_what_nayaflow_wrote_to_the_board():
    want = {0x2F: "BT_OUT", 0x30: "USB_DEVICE", 0x47: "BT_OUT", 0x48: "USB_DEVICE"}
    for pos, code in want.items():
        typ, param = _rec(code)
        assert (typ, param.hex()) == (0x08, ON_BOARD[pos]), f"pos {pos:#04x}"
    print("  the four records on layer 2 are reproduced byte for byte")


def test_an_unknown_output_is_still_dropped_with_a_reason():
    assert _rec("BT_NEXT") is None
    reason = F._drop_reason("out", "BT_NEXT")
    assert "BT_OUT" in reason and "USB_DEVICE" in reason
    assert "not yet written" not in reason, "the old 'pending' wording must be gone"
    print("  an output we have no selector for is reported, not guessed")


if __name__ == "__main__":
    for fn in (test_both_outputs_encode_to_the_vendor_bytes,
               test_round_trip_through_the_decoder,
               test_matches_what_nayaflow_wrote_to_the_board,
               test_an_unknown_output_is_still_dropped_with_a_reason):
        print(fn.__name__)
        fn()
    print("\nOK")
