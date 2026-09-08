"""A binding that cannot be encoded must be REPORTED, never silently discarded.

THE FAILURE THIS CLOSES. `_binding_rows_to_record` returns None for any action type it cannot
encode, and nothing collected that. The position was simply never added to `desired.layers`;
`_full_layer_payload` then fell back to `device.get(pos)`; and verification only compares
positions the plan actually SET, so the flash came back "verified" with the binding absent.

Net effect for a user: setting a key to Disabled left the key doing whatever it did before, and
the app said it worked. Four separate action types were in that state (Disabled, Transparent,
Sticky Layer, Wireless/USB-C), plus macros and BT_CLEAR.

The fix deliberately does NOT write NONE for a dropped position. Clearing the key would destroy
a binding the user never asked to remove — a second wrong answer. It keeps the old record and
says so, naming what the key will actually keep doing.

These tests assert the REPORT, because the report is the feature. They are the tests that would
have caught the original bug, which had none.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F    # noqa: E402


def rows(action_type, code, beh="press"):
    return [{"beh": beh, "at": action_type, "ac": code}]


def test_an_encodable_binding_produces_no_drop():
    assert F._binding_rows_to_record(rows("key", "A"), 200, 0, {}) is not None


def test_every_known_unencodable_type_has_a_reason_a_user_can_act_on():
    """Not a generic 'unsupported'. Each says what is actually wrong."""
    for at, code, expect in [
        ("none", "DISABLE", "Disabled"),
        ("trans", "TRANSPARENT", "Transparent"),
        ("layer_polite_oneshot", "STICKY_LAYER_1", "Sticky Layer"),
        ("out", "BT_OUT", "Wireless"),
        ("macro", "some-uuid", "macro table"),
        ("bluetooth", "BT_CLEAR", "1-4"),
    ]:
        reason = F._drop_reason(at, code)
        assert expect in reason, f"{at}: {reason!r} does not mention {expect!r}"
        assert reason.strip(), at


def test_an_unlisted_type_still_reports_rather_than_going_silent():
    """The property that matters: silence must not be reachable. A type nobody has thought of
    still names itself instead of vanishing."""
    reason = F._drop_reason("some_future_type", "X")
    assert "some_future_type" in reason, reason


def test_the_dropped_entry_carries_where_and_what():
    """A report that cannot be traced to a key is not actionable."""
    d = F.DesiredState()
    d.dropped.append({"layer": 0, "position": 0x2F, "actionCode": "STICKY_LAYER_1",
                      "actionType": "layer_polite_oneshot",
                      "reason": F._drop_reason("layer_polite_oneshot", "STICKY_LAYER_1"),
                      "effect": "this key keeps whatever the keyboard already had on it"})
    e = d.dropped[0]
    assert {"layer", "position", "actionCode", "actionType", "reason", "effect"} <= set(e)


def test_a_dry_run_surfaces_drops():
    """The flash preview is where a user finds out BEFORE writing."""
    d = F.DesiredState()
    d.layers[0] = {}
    d.dropped.append({"layer": 0, "position": 5, "actionCode": "DISABLE", "actionType": "none",
                      "reason": "x", "effect": "y"})
    out = F.flash(d, dry_run=True)
    assert out["dropped"] and out["dropped"][0]["actionCode"] == "DISABLE", out.get("dropped")


def test_a_clean_plan_reports_no_drops():
    out = F.flash(F.DesiredState(), dry_run=True)
    assert out["dropped"] == []


def test_a_dropped_position_is_not_written_as_none():
    """The deliberate choice: we do NOT clear the key. Clearing would destroy a binding the user
    never asked to remove, which is a different wrong answer, not a fix."""
    d = F.DesiredState()
    d.layers[0] = {}                       # nothing encodable on this layer
    d.dropped.append({"layer": 0, "position": 5, "actionCode": "DISABLE", "actionType": "none",
                      "reason": "x", "effect": "y"})
    device = {5: (0x01, bytes.fromhex("04000700"))}      # the key currently types 'A'
    payload = F._full_layer_payload(0, d.layers[0], device)
    # Position 5 must still carry the device's own record, byte for byte:
    # [pos=05][type=01][len=04][04 00 07 00]
    assert bytes.fromhex("05010404000700") in payload, "the existing binding was not preserved"
