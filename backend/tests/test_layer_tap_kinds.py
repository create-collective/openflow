"""The two bytes at the front of a hold-tap body are per-slot behaviour KINDS (SCRUM-110).

Every OneKey record we had captured opened with `01 01`, and both the decoder and the encoder
treated that as a constant. Then a stock board's Enter and Backspace keys read back as tap +
`RAW_p00:02m00`. Their raw records, from the SCRUM-108 postflight capture of the warranty board:

    pos 0x07  type 0x03  05 01 00 c8 00 | 02000000 | 00000000 | 28000700 | 00000000   tap RETURN
    pos 0x08  type 0x03  05 01 00 c8 00 | 02000000 | 00000000 | 2a000700 | 00000000   tap BACKSPACE

`05` is LAYER_HOLD and `01` is KEY_PRESS: hold = momentary layer, tap = keypress, the hold slot
carrying a layer INDEX. ZMK's layer-tap -- hold Enter or Backspace to reach layer 2. Fed to the
keypress decoder, a layer index of 2 is page 0, uid 2: `RAW_p00:02m00`. And the encoder could
not write it back, so a flash of the read profile dropped both keys (safely, but with a reason
that blamed the tap).

A census of every raw keymap on disk found exactly two kinds in the wild, 01 and 05. Anything
else stays RAW with the kind visible. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F          # noqa: E402
from openflow_backend.device import keymap_read as kr   # noqa: E402
from openflow_backend.device import remap as R          # noqa: E402

RETURN_LT2 = bytes.fromhex("050100c80002000000000000002800070000000000")
BACKSPACE_LT2 = bytes.fromhex("050100c80002000000000000002a00070000000000")
LAYER2 = "61bcc6b7-ee73-4d86-8aa0-53a770ddb360"           # the board's third layer
ORDER_TO_LAYER = {0: "l0", 1: "l1", 2: LAYER2}
LAYER_ORDER = {v: k for k, v in ORDER_TO_LAYER.items()}


def test_the_stock_layer_tap_decodes_as_tap_plus_hold_layer():
    got = kr.translate(0x03, RETURN_LT2, ORDER_TO_LAYER)
    assert got == [("press", "key", "RETURN"),
                   ("hold", "layer_polite_hold", f"MO_LAYER_{LAYER2}")], got
    assert kr.translate(0x03, BACKSPACE_LT2, ORDER_TO_LAYER)[0] == ("press", "key", "BACKSPACE")


def test_it_encodes_back_byte_for_byte():
    """A profile read from a stock board and flashed back must not rewrite these keys, so the
    encoder has to produce the board's own bytes: the 0x03 form, kind 05 01, layer index."""
    rows = [{"beh": "press", "at": "key", "ac": "RETURN"},
            {"beh": "hold", "at": "layer_polite_hold", "ac": f"MO_LAYER_{LAYER2}"}]
    assert F._binding_rows_to_record(rows, 200, 0, LAYER_ORDER) == (R.HOLD_TAP_HOME, RETURN_LT2)


def test_round_trip_is_the_identity():
    for raw in (RETURN_LT2, BACKSPACE_LT2):
        acts = kr.translate(0x03, raw, ORDER_TO_LAYER)
        rows = [{"beh": b, "at": at, "ac": code} for b, at, code in acts]
        assert F._binding_rows_to_record(rows, 200, 0, LAYER_ORDER) == (R.HOLD_TAP_HOME, raw)


def test_a_layer_slot_of_zeros_is_layer_zero_not_unset():
    """The SCRUM-96 rule (four zero bytes = no binding) belongs to KEYPRESS slots. In a layer
    slot the same bytes are a real target, the base layer."""
    raw = bytes.fromhex("050100c80000000000000000002800070000000000")
    assert ("hold", "layer_polite_hold", "MO_LAYER_l0") in kr.translate(0x03, raw, ORDER_TO_LAYER)


def test_a_keypress_slot_of_zeros_is_still_unset():
    raw = bytes.fromhex("010100c80000000000000000002800070000000000")
    assert kr.translate(0x03, raw, ORDER_TO_LAYER) == [("press", "key", "RETURN")]


def test_an_unseen_kind_stays_raw_with_the_kind_visible():
    """Guessing is what produced RAW_p00:02m00. A kind nobody has captured keeps its bytes and
    names its kind, so the next capture can identify it and a re-flash refuses it."""
    raw = bytes.fromhex("0c0100c80003000000000000002800070000000000")   # 0c = LAYER_TO in a hold
    got = kr.translate(0x03, raw, ORDER_TO_LAYER)
    assert got[0] == ("press", "key", "RETURN")
    assert got[1][0] == "hold" and str(got[1][2]) == "RAW_k0c:03000000"
    with pytest.raises(R.RemapEncodeError):
        R.encode_keypress("key", got[1][2])


def test_onekey_records_are_unchanged():
    """The existing 01 01 form, both banks, byte-identical to before this change."""
    body = R.encode_holdtap_param(R.HOLD_TAP_ONEKEY, 1, 200,
                                  bytes.fromhex("05000700"), bytes.fromhex("04000700"))
    assert body.hex() == "c80003010101c8000500070000000000" + "0400070000000000"
    assert kr.translate(0x10, body, {}) == [("press", "key", "A"), ("hold", "key", "B")]


def test_a_layer_hold_that_points_nowhere_is_dropped_not_guessed():
    rows = [{"beh": "press", "at": "key", "ac": "RETURN"},
            {"beh": "hold", "at": "layer_polite_hold", "ac": "MO_LAYER_deleted"}]
    with pytest.raises(R.RemapEncodeError, match="not in this profile"):
        F._binding_rows_to_record(rows, 200, 0, LAYER_ORDER)


def test_the_drop_report_names_the_binding_that_failed():
    """RETURN encoded fine; its hold did not. The report used to say 'no encoder for action
    type key' about RETURN, which sent the user looking at the wrong binding."""
    rows = [{"beh": "press", "at": "key", "ac": "RETURN"},
            {"beh": "hold", "at": "key", "ac": "RAW_p00:02m00"}]
    culprit = F._failing_row(rows, 200, 0, LAYER_ORDER)
    assert culprit["beh"] == "hold" and culprit["ac"] == "RAW_p00:02m00"
    assert "cannot name yet" in F._drop_reason(culprit["at"], culprit["ac"])


def test_the_drop_report_still_names_the_press_when_the_press_is_the_problem():
    rows = [{"beh": "press", "at": "macro", "ac": "M1"},
            {"beh": "hold", "at": "key", "ac": "B"}]
    assert F._failing_row(rows, 200, 0, LAYER_ORDER)["beh"] == "press"
