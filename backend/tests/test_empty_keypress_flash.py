"""A key the board holds as an all-zero keypress must not abort the flash (SCRUM-95).

Reported from the field twice on 2026-09-19. A tester set one key to a tap of LCTRL + LSHIFT + V
and nothing else; the board came back carrying a hold-tap record whose HOLD slot was all zeros.
Our decoder names those four bytes `RAW_p00:00m00` (remap.EMPTY_KEYPRESS), the importer stored
them as a hold binding, and the next flash preview died with:

    flash preview failed: unknown key 'RAW_p00:00m00'

before a single byte reached the device. One key took down the whole board's flash, and the
message named no position, so the tester had to find the key by renaming profiles and re-reading
until he spotted it.

Two separate properties are asserted here, because they fail differently:

  * EMPTY_KEYPRESS is ENCODABLE. The name is the decoder's own word for `00000000`, so the
    round trip is exact -- read it, write it back unchanged. Dropping the key instead would
    also stop the crash, and would be wrong: it would silently stop preserving what is on
    the board.
  * anything else unencodable is a DROP, not a crash. The caller was always written for that
    path (it reports the key and what it will keep doing); the encoder just had no way to
    reach it without raising.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

CHORD = "LCTRL + LSHIFT + V"          # the tester's actual binding
POS = 67                              # LH4, the key it happened on


def row(beh, at, ac):
    return {"beh": beh, "at": at, "ac": ac, "p": POS}


def test_empty_keypress_encodes_to_the_zeros_it_names():
    """The whole bug in one line: the code IS the bytes, so there is nothing to refuse."""
    assert R.EMPTY_KEYPRESS == "RAW_p00:00m00"
    assert F._keypress("key", R.EMPTY_KEYPRESS) == bytes(4)


def test_the_reported_key_no_longer_aborts_the_flash():
    """Tap chord + a hold slot the board holds as zeros. This raised before the fix."""
    rec = F._binding_rows_to_record(
        [row("tap", "shortcut_alias", CHORD), row("hold", "keypress", R.EMPTY_KEYPRESS)],
        200, 0, {})
    assert rec is not None
    typ, param = rec
    assert typ == R.HOLD_TAP_HOME   # tap+hold with no second bank (test_home_row_record_type)
    # The tap survives intact and the hold is written back as the zeros it came from.
    assert R.encode_keypress("shortcut_alias", CHORD).hex() in param.hex()
    assert param.hex().count("00000000") >= 1


def test_a_whole_key_bound_to_nothing_still_writes():
    """The Tune's LED-brightness gestures read back this way too, not just hold slots."""
    typ, param = F._binding_rows_to_record([row("tap", "key", R.EMPTY_KEYPRESS)], 200, 0, {})
    assert (typ, param) == (R.KEY_PRESS, bytes(4))


def test_the_second_bank_takes_it_too():
    """Double-tap and tap+hold share the hold-tap shape and had the same unguarded encode."""
    rec = F._second_bank_record(
        [row("double_tap", "key", R.EMPTY_KEYPRESS), row("tap_hold", "shortcut_alias", CHORD)],
        200, 0)
    assert rec is not None and rec[0] == R.HOLD_TAP_ONEKEY


def test_an_unnameable_record_is_dropped_rather_than_fatal():
    """EMPTY_KEYPRESS is known bytes. A RAW_ code we have never decoded is not, and guessing
    at it would be inventing a binding -- so that key is reported and left alone."""
    with pytest.raises(R.RemapEncodeError):
        F._binding_rows_to_record([row("tap", "key", "RAW_ff11ee22")], 200, 0, {})
    reason = F._drop_reason("key", "RAW_ff11ee22")
    assert "cannot name" in reason, reason


def test_the_drop_reason_does_not_blame_the_action_type():
    """The type is fine; the CODE is the thing we cannot write. Saying 'key bindings cannot be
    written' would send someone looking for a missing feature."""
    assert F._drop_reason("key", "RAW_ff11ee22") != F._DROP_REASONS.get("key", object())
