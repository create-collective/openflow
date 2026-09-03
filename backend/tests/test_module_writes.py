"""Targeted module-config writes: slot resolution, button rebinds, and axis inversion.

Everything here is checked against the real 2026-09-02 capture rather than our own
round-trip, so a regression shows up as a difference from what the device accepted.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import module_fields as mf  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

WRITES = json.loads((_REPO / "device" / "out" / "track-swap-writes.json").read_text())
TRACK_SLOT = bytes.fromhex(WRITES["4"])
TRACK_FIELDS = {f: (t, v) for f, t, v in kr.parse_records(TRACK_SLOT[1:])}


def test_slot_map_resolves_by_uuid():
    m = F.slot_map_for(bytes.fromhex(WRITES["list"]))
    assert m["a7d0eb1c-a75a-4c88-9dc1-2d00aff33d38"] == 4, "Track Left should resolve to slot 4"
    assert m["9e69c41f-8da6-4441-b5c1-cb9a75319a28"] == 3, "Touch Windows should resolve to slot 3"
    print(f"  {len(m)} module configs resolved by uuid -> slot")


def test_button_write_is_sparse_and_matches_the_captured_shape():
    op = F.module_button_write(4, "TRACK", {"tap:track:button_1": "M2"})
    recs = list(kr.parse_records(op.payload[1:]))
    assert op.payload[0] == 4, "payload must start with the slot byte"
    assert len(recs) == 1, "a one-button change must be a one-field write"
    field, typ, value = recs[0]
    assert (field, typ) == (0x0B, R.TWO_WORD)
    assert R.decode_mouse_button(value) == "M2"
    # same framing as the 4-byte single-field write NayaFlow was captured sending
    captured_sparse = bytes.fromhex(WRITES["1"])
    assert len(list(kr.parse_records(captured_sparse[1:]))) == 1
    assert op.payload[:1] + op.payload[1:2] == bytes([4, 0x0B])
    print(f"  button write: {op.payload.hex()} ({op.label})")


def test_button_write_rejects_unknown_gesture_and_code():
    for bad in ({"tap:track:button_9": "M1"}, {"tap:tune:1_finger": "M1"}):
        try:
            F.module_button_write(4, "TRACK", bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should have rejected {bad}")
    try:
        F.module_button_write(4, "TRACK", {"tap:track:button_1": "M9"})
    except R.RemapEncodeError:
        pass
    else:
        raise AssertionError("should have rejected mouse button M9")
    print("  unknown gestures and mouse codes are refused")


def test_axis_invert_swaps_one_pair_and_is_its_own_undo():
    # Track rotate = category 4 (fields 0x09/0x0a): +1 then -1 on the device today.
    before = {f: R.decode_two_word(v)[1] for f, (t, v) in TRACK_FIELDS.items() if f in (0x09, 0x0A)}
    assert before == {0x09: 1, 0x0A: -1}, f"unexpected starting directions {before}"

    op = F.module_axis_invert(4, "TRACK", TRACK_FIELDS, 4)
    recs = {f: (t, v) for f, t, v in kr.parse_records(op.payload[1:])}
    assert set(recs) == {0x09, 0x0A}, "inversion must touch exactly the one axis pair"
    after = {f: R.decode_two_word(v)[1] for f, (t, v) in recs.items()}
    assert after == {0x09: -1, 0x0A: 1}, f"directions did not swap: {after}"
    for f, (t, v) in recs.items():
        assert R.decode_two_word(v)[0] == 4, "category must be preserved"

    # applying it again returns the original -- so the UI toggle is reversible
    again = F.module_axis_invert(4, "TRACK", {**TRACK_FIELDS, **recs}, 4)
    back = {f: R.decode_two_word(v)[1] for f, t, v in kr.parse_records(again.payload[1:])}
    assert back == before, f"invert is not its own undo: {back}"

    # the buttons and the other two axes are untouched
    assert not (set(recs) & set(mf.mouse_button_fields("TRACK").values()))
    print(f"  rotate inverted: {before} -> {after}, and back again")


if __name__ == "__main__":
    for fn in (test_slot_map_resolves_by_uuid,
               test_button_write_is_sparse_and_matches_the_captured_shape,
               test_button_write_rejects_unknown_gesture_and_code,
               test_axis_invert_swaps_one_pair_and_is_its_own_undo):
        print(fn.__name__)
        fn()
    print("\nOK")
