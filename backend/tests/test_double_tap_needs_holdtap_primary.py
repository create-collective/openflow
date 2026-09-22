"""Double-tap only fires if the PRIMARY record is a hold-tap (SCRUM-109).

The four behaviours are two records 0x52 apart (test_second_bank.py): tap + hold in the primary
bank, double-tap + tap+hold in the shadow. What nobody had tested is a key with a double-tap and
NO hold. The encoder wrote its primary as a plain KEY_PRESS, and a plain keypress fires the
instant it is pressed -- there is no tapping-term window in which a second tap can be noticed, so
the shadow is never consulted.

Measured on the warranty board, 2026-09-21. Tap A / Double-tap B / Hold empty, flashed and
verified on the wire as

    pos 0x37  type 0x01  04000700                                 plain keypress A
    pos 0x89  type 0x10  c800 03 01 01 01 c800 | 00000000 | .. | 05000700   shadow: hold empty, tap B

and the owner's double tap typed "aa", never "b". Filling Hold with anything made it work,
because that flipped the primary to a hold-tap. The fix writes the hold-tap anyway, with the hold
slot EMPTY -- four zero bytes, the device's own convention for an unset half (SCRUM-96), which
reads back as "no hold" rather than an invented one.

A tap-only key is deliberately left as a plain keypress: promoting it would add tapping-term
latency to a key with nothing to wait for. No hardware.
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
EMPTY = bytes(4)


def _rows(*acts):
    return [{"beh": beh, "at": "key", "ac": code} for beh, code in acts]


def _slots(param: bytes) -> tuple[bytes, bytes]:
    """(hold, tap) of a hold-tap param, whichever header length it carries."""
    h = len(param) - 16
    return param[h:h + 4], param[h + 8:h + 12]


def test_tap_plus_double_tap_gets_a_hold_tap_primary_with_an_empty_hold():
    typ, param = F._binding_rows_to_record(_rows(("press", "A"), ("double_tap", "B")),
                                           TERM, FLAVOUR, {})
    assert typ == R.HOLD_TAP_ONEKEY, "a plain keypress never sees the second bank"
    hold, tap = _slots(param)
    assert tap == A and hold == EMPTY
    # Byte-exact against the shadow the board accepted: same header, empty half, real key.
    assert param == R.encode_holdtap_param(R.HOLD_TAP_ONEKEY, FLAVOUR, TERM, EMPTY, A)


def test_tap_plus_tap_hold_is_promoted_the_same_way():
    typ, param = F._binding_rows_to_record(_rows(("press", "A"), ("tap_hold", "C")),
                                           TERM, FLAVOUR, {})
    assert typ == R.HOLD_TAP_ONEKEY and _slots(param) == (EMPTY, A)


def test_the_ui_spelling_of_tap_hold_counts_too():
    typ, _ = F._binding_rows_to_record(_rows(("press", "A"), ("tap+hold", "C")), TERM, FLAVOUR, {})
    assert typ == R.HOLD_TAP_ONEKEY


def test_a_tap_only_key_stays_a_plain_keypress():
    """Nothing to wait for, so no tapping term. The SCRUM-96 shape must not be written
    back for a key the user gave one behaviour."""
    assert F._binding_rows_to_record(_rows(("press", "A")), TERM, FLAVOUR, {}) == (R.KEY_PRESS, A)


def test_a_real_hold_is_unchanged():
    typ, param = F._binding_rows_to_record(_rows(("press", "A"), ("hold", "B"), ("double_tap", "C")),
                                           TERM, FLAVOUR, {})
    assert typ == R.HOLD_TAP_ONEKEY and _slots(param) == (B, A)


def test_the_promoted_primary_reads_back_as_tap_only():
    """The round trip must not re-invent a hold (SCRUM-96): an empty half decodes to nothing."""
    typ, param = F._binding_rows_to_record(_rows(("press", "A"), ("double_tap", "B")),
                                           TERM, FLAVOUR, {})
    assert kr.translate(typ, param, {}) == [("press", "key", "A")]


def test_the_shadow_is_still_written_beside_it():
    rows = _rows(("press", "A"), ("double_tap", "B"))
    second = F._second_bank_record(rows, TERM, FLAVOUR)
    assert second is not None and second[0] == R.HOLD_TAP_ONEKEY
    assert _slots(second[1]) == (EMPTY, B), "double-tap is the shadow's TAP slot"


def test_a_tap_that_is_not_a_keypress_is_not_promoted():
    """A layer switch with a double-tap is not something the hold-tap encoder can express yet
    (a layer in a hold-tap slot is SCRUM-110). It must fall through to its own encoder rather
    than be forced into a keypress slot."""
    rows = [{"beh": "press", "at": "layer_rude_toggle", "ac": "TO_LAYER_x"},
            {"beh": "double_tap", "at": "key", "ac": "B"}]
    assert F._binding_rows_to_record(rows, TERM, FLAVOUR, {"x": 1}) == (R.LAYER_TO, R.encode_layer_param(1))
