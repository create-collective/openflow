"""Double-tap only fires if the PRIMARY record is wrapped (SCRUM-109).

The four behaviours are two records 0x52 apart (test_second_bank.py): tap + hold in the primary
bank, double-tap + tap+hold in the shadow. What nobody had tested is a key with a double-tap and
NO hold. The encoder wrote its primary as a plain KEY_PRESS, and a plain keypress fires the
instant it is pressed -- there is no tapping-term window in which a second tap can be noticed, so
the shadow is never consulted.

Measured on the warranty board, 2026-09-21. Tap A / Double-tap B / Hold empty, flashed and
verified on the wire as

    pos 0x37  type 0x01  04000700                                 plain keypress A
    pos 0x89  type 0x10  c800 03 01 01 01 c800 | 00000000 | .. | 05000700   shadow: hold empty, tap B

and the owner's double tap typed "aa", never "b". Filling Hold with anything made it work. The fix
then was to write a 24-byte hold-tap with an EMPTY hold.

NayaCore's own code (read 2026-09-26, see test_nayacore_onekey_forms.py) does it differently and
smaller: whenever a key has a double-tap or tap+hold it puts the key's record, whatever it is,
inside the 0x10 wrapper [term u16][inner type][inner param]. The wrapper is the part that waits.
So Tap A + Double-tap B is 7 bytes a bank, and a tap that is not a keypress (a layer switch) gets
its double-tap too, which the hold-tap workaround could not do.

A tap-only key is deliberately left bare: wrapping it would add tapping-term latency to a key with
nothing to wait for. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F          # noqa: E402
from openflow_backend.device import keymap_read as kr   # noqa: E402
from openflow_backend.device import remap as R          # noqa: E402

TERM, FLAVOUR = 200, 1
A, B, C = bytes.fromhex("04000700"), bytes.fromhex("05000700"), bytes.fromhex("06000700")
WRAP = (TERM).to_bytes(2, "little")


def _rows(*acts):
    return [{"beh": beh, "at": "key", "ac": code} for beh, code in acts]


def test_tap_plus_double_tap_wraps_the_tap():
    rec = F._binding_rows_to_record(_rows(("press", "A"), ("double_tap", "B")), TERM, FLAVOUR, {})
    assert rec == (R.HOLD_TAP_ONEKEY, WRAP + bytes([R.KEY_PRESS]) + A), \
        "a bare keypress never sees the second bank; the wrapper around it is what waits"


def test_tap_plus_tap_hold_wraps_it_the_same_way():
    rec = F._binding_rows_to_record(_rows(("press", "A"), ("tap_hold", "C")), TERM, FLAVOUR, {})
    assert rec == (R.HOLD_TAP_ONEKEY, WRAP + bytes([R.KEY_PRESS]) + A)


def test_the_ui_spelling_of_tap_hold_counts_too():
    typ, _ = F._binding_rows_to_record(_rows(("press", "A"), ("tap+hold", "C")), TERM, FLAVOUR, {})
    assert typ == R.HOLD_TAP_ONEKEY


def test_a_tap_only_key_stays_a_plain_keypress():
    """Nothing to wait for, so no tapping term."""
    assert F._binding_rows_to_record(_rows(("press", "A")), TERM, FLAVOUR, {}) == (R.KEY_PRESS, A)


def test_a_real_hold_is_a_wrapped_pair():
    typ, param = F._binding_rows_to_record(_rows(("press", "A"), ("hold", "B"), ("double_tap", "C")),
                                           TERM, FLAVOUR, {})
    assert typ == R.HOLD_TAP_ONEKEY and param[2] == R.HOLD_TAP_HOME
    assert kr.translate(typ, param, {}) == [("press", "key", "A"), ("hold", "key", "B")]


def test_the_wrapped_primary_reads_back_as_tap_only():
    """The round trip must not invent a hold (SCRUM-96)."""
    typ, param = F._binding_rows_to_record(_rows(("press", "A"), ("double_tap", "B")),
                                           TERM, FLAVOUR, {})
    assert kr.translate(typ, param, {}) == [("press", "key", "A")]


def test_the_shadow_is_the_double_tap_on_its_own():
    """A double-tap with no tap+hold is a record of its own in the shadow, wrapped, not a pair
    with an empty half."""
    second = F._second_bank_record(_rows(("press", "A"), ("double_tap", "B")), TERM, FLAVOUR)
    assert second == (R.HOLD_TAP_ONEKEY, WRAP + bytes([R.KEY_PRESS]) + B)


def test_a_tap_that_is_not_a_keypress_gets_its_double_tap_too():
    """A layer switch with a double-tap could not be forced into a hold-tap's keypress slot, so it
    used to be written bare -- and a bare record never consults the second bank. Wrapped, it does."""
    rows = [{"beh": "press", "at": "layer_rude_toggle", "ac": "TO_LAYER_x"},
            {"beh": "double_tap", "at": "key", "ac": "B"}]
    assert F._binding_rows_to_record(rows, TERM, FLAVOUR, {"x": 1}) == \
        (R.HOLD_TAP_ONEKEY, WRAP + bytes([R.LAYER_TO]) + R.encode_layer_param(1))
