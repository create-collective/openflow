"""An empty half of a hold-tap record is UNSET, not a binding (SCRUM-96).

A tester set one key to a tap of LCTRL + LSHIFT + V and nothing else. The board stored it as a
hold-tap whose HOLD half was four zero bytes, and the read turned that into a hold binding of
RAW_p00:00m00. The editor showed tap+hold on a key he had never given a hold action, he could
not clear it from inside the app, and the next flash wrote the empty hold straight back.

That last part is what made it worth fixing rather than tolerating: the invention survived every
round trip. SCRUM-95 stopped the flash CRASHING on it, which made the loop quieter, not shorter.

The distinction that has to survive: a whole key whose KEY_PRESS record is all zeros still
decodes as a binding. That is a different record type and a real thing the board carries -- the
Tune gestures NayaFlow labels LED Brightness, where the keyboard performs the action itself and
reports nothing to the host.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as KR  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

CHORD = "LCTRL + LSHIFT + V"
TAP_KP = R.encode_keypress("shortcut_alias", CHORD)


def holdtap(hold_kp: bytes, tap_kp: bytes) -> bytes:
    return R.encode_holdtap_param(R.HOLD_TAP_ONEKEY, 0, 200, hold_kp, tap_kp)


def slots(param: bytes):
    """{behaviour: code} for one hold-tap record, through the real decoder."""
    return {beh: code for beh, _at, code in
            KR.translate(R.HOLD_TAP_ONEKEY, param, {})}


def test_the_reported_key_decodes_as_tap_only():
    """The exact shape from the report: a chord on tap, zeros on hold."""
    out = slots(holdtap(bytes(4), TAP_KP))
    assert list(out) == ["press"]
    assert out["press"] == CHORD
    assert "hold" not in out, "a hold the user never set must not appear"


def test_an_empty_tap_half_is_dropped_too():
    """The second bank writes an empty TAP when a key has a tap+hold but no double-tap."""
    out = slots(holdtap(TAP_KP, bytes(4)))
    assert list(out) == ["hold"]
    assert out["hold"] == CHORD


def test_a_real_hold_tap_is_untouched():
    out = slots(holdtap(R.encode_keypress("key", "A"), TAP_KP))
    assert out == {"press": CHORD, "hold": "A"}


def test_a_whole_key_of_zeros_still_decodes():
    """The distinction that must survive. A KEY_PRESS record of zeros is a real binding: the
    board carries it where the keyboard handles the action itself (LED brightness), and that
    branch is deliberately untouched."""
    got = KR.translate(R.KEY_PRESS, bytes(4), {})
    assert got and got[0][0] == "press", "an empty KEY_PRESS must still produce a binding"


def test_the_round_trip_no_longer_reinvents_the_hold():
    """Read -> app rows -> flash -> read. Before the fix this cycle never converged: each read
    recreated the phantom and each flash wrote it back."""
    first = slots(holdtap(bytes(4), TAP_KP))
    rows = [{"beh": b, "at": "shortcut_alias", "ac": c, "p": 67} for b, c in first.items()]
    typ, param = F._binding_rows_to_record(rows, 200, 0, {})
    assert typ == R.KEY_PRESS, "a tap-only key should go back as a plain keypress"
    assert param == TAP_KP
    # and reading THAT back gives the same single binding, so the cycle is stable
    again = KR.decode_keypress(param)
    assert again[1] == CHORD
