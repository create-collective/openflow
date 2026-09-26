"""Disabled, Transparent, and unbinding a module gesture must actually reach the keyboard.

Before this, all three were no-ops that looked like successes:

  * Setting a key to **Disabled** returned None from the encoder, so the position was never
    added to the plan, `_full_layer_payload` fell back to the device's own record, and the key
    KEPT ITS PREVIOUS BINDING. Same for **Transparent**.
  * Unbinding a **module gesture** hit `if not code: continue` in `module_layout.overlay`, so the
    template's old value passed through and the field kept what it had.

None of these needed new protocol work — they are records this file already emits elsewhere:

  * NONE (0x07, empty) comes back ~220 times in every board read, and NayaCore has been captured
    writing it three ways: blanking whole layers (flash3-analysis), a sparse `49 07 00` edit, and
    the `2e 07 00` from the macro investigation. `_full_layer_payload` writes it today for
    unmodelled positions.
  * TRANS (0x0e, empty) appears 23-25 times per read and was captured from NayaCore in both
    full-layer (flash2-analysis) and sparse form.
  * The module clear `[field] 07 00` was captured twice: `01 0b 07 00` (the "enable all modules"
    flash that silently cleared Track Right button 1 — docs/phase-c-test-plan.md C2b) and
    `08 07 00` in the flash-3 table.

The bytes are asserted exactly rather than "something was returned", because the short-param
finding showed a plausible-looking record can be accepted and still inert.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F             # noqa: E402
from openflow_backend.device import module_layout as ML    # noqa: E402
from openflow_backend.device import remap as R             # noqa: E402


def rows(action_type, code):
    return [{"beh": "press", "at": action_type, "ac": code}]


# --- keys ------------------------------------------------------------------------------------ #

def test_disabled_encodes_to_the_none_record():
    assert F._binding_rows_to_record(rows("none", "DISABLE"), 200, 0, {}) == (0x07, b"")


def test_transparent_encodes_to_the_trans_record():
    assert F._binding_rows_to_record(rows("trans", "TRANSPARENT"), 200, 0, {}) == (0x0E, b"")


def test_neither_is_dropped_any_more():
    """The regression: both used to return None and vanish."""
    for at, code in (("none", "DISABLE"), ("trans", "TRANSPARENT")):
        assert F._binding_rows_to_record(rows(at, code), 200, 0, {}) is not None, at


def test_a_disabled_key_no_longer_inherits_its_old_binding():
    """The user-visible failure, end to end: the device has 'A' on position 5, the profile says
    Disabled, and the written layer must carry NONE rather than the device's keypress."""
    d = F.DesiredState()
    d.layers[0] = {5: F._binding_rows_to_record(rows("none", "DISABLE"), 200, 0, {})}
    device = {5: (0x01, bytes.fromhex("04000700"))}          # currently types 'A'
    payload = F._full_layer_payload(0, d.layers[0], device)
    assert bytes.fromhex("050700") in payload, "position 5 was not written as NONE"
    assert bytes.fromhex("05010404000700") not in payload, "the old 'A' binding survived"


def test_transparent_survives_a_recovery_flash():
    """mode='recovery' has no device read to fall back on, so before this every TRANS on the
    board became NONE. With an encoder there is something real to write."""
    d = F.DesiredState()
    d.layers[0] = {9: F._binding_rows_to_record(rows("trans", "TRANSPARENT"), 200, 0, {})}
    payload = F._full_layer_payload(0, d.layers[0], None)    # None = no device read
    assert bytes.fromhex("090e00") in payload, payload.hex()


# --- module gestures -------------------------------------------------------------------------- #

def _tune_tap_field():
    from openflow_backend.device import module_fields as MF
    fields = MF.writable_fields("TUNE")
    gesture = next(g for g in fields if g.startswith("tap:tune:1_finger"))
    return gesture, fields[gesture]


def test_unbinding_a_module_gesture_clears_the_field():
    gesture, idx = _tune_tap_field()
    template = {idx: (R.KEY_PRESS, bytes.fromhex("04000700"))}
    out = ML.overlay(template, "TUNE", {gesture: ""})
    assert out[idx] == (0x07, b""), out[idx]


def test_a_gesture_absent_from_bindings_is_written_unbound():
    """Reversed on 2026-09-26. This used to keep the template's value for a gesture the profile
    had no row for, so a flash would not "wipe fields the profile never mentioned". But the read
    calls a gesture with no row unbound, and the app shows it that way too (its backfill inserts
    an empty row for exactly these gestures), so keeping the board's value meant every read of
    such a profile disagreed with its own flash and minted an "(on board)" copy with no edit
    made (tests/test_module_flash_read_parity.py). It covers only the gestures OpenFlow models;
    every other field of the slot still passes through."""
    gesture, idx = _tune_tap_field()
    template = {idx: (R.KEY_PRESS, bytes.fromhex("04000700"))}
    out = ML.overlay(template, "TUNE", {})
    assert out[idx] == (R.NONE_BEH, b""), "a gesture with no row is unbound, as the read calls it"


def test_binding_a_gesture_still_works():
    gesture, idx = _tune_tap_field()
    out = ML.overlay({}, "TUNE", {gesture: "M1"})
    assert out[idx][0] == R.TWO_WORD and out[idx][1] == R.encode_mouse_button("M1")
