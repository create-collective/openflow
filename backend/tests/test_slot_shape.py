"""assert_track_shape must accept a real Track slot -- including a damaged one -- and refuse
anything else. This is the check standing between a module write and another module's config,
because the device's own list is not trustworthy (it mislabels a slot on the reference device).
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
from openflow_backend.device import remap as R  # noqa: E402

WRITES = json.loads((_REPO / "device" / "out" / "track-swap-writes.json").read_text())


def fields(slot_key):
    return {f: (t, v) for f, t, v in kr.parse_records(bytes.fromhex(WRITES[slot_key])[1:])}


def test_accepts_a_clean_track():
    assert F.assert_track_shape(fields("4")) == 0, "a 15-field Track has no trailing junk"
    print("  clean 15-field Track accepted")


def test_accepts_a_track_with_a_cleared_button_and_trailing_junk():
    """The exact shape of slot 1 on the reference device: a Track config with button_1
    cleared by NayaFlow and 21 orphaned Touch fields left on the tail."""
    track, touch = fields("4"), fields("3")
    damaged = dict(track)
    damaged[0x0B] = (R.NONE_BEH, b"")                      # NayaFlow's clear
    damaged.update({f: v for f, v in touch.items() if f > 0x0E})   # orphaned tail
    trailing = F.assert_track_shape(damaged)
    assert trailing == len(damaged) - 15, f"expected the tail to be reported, got {trailing}"
    assert trailing > 0
    print(f"  damaged Track accepted, {trailing} trailing fields reported")


def test_refuses_a_touch_slot():
    for key, why in (("3", "Touch config"), ("1", "single-field sparse write")):
        try:
            F.assert_track_shape(fields(key))
        except F.SlotShapeError:
            continue
        raise AssertionError(f"a {why} was accepted as a Track")
    print("  Touch config and a stray sparse payload both refused")


def test_refuses_a_track_missing_an_axis_pair():
    broken = dict(fields("4"))
    broken[0x0A] = (R.TWO_WORD, R.encode_two_word(4, 1))   # both halves of the pair now +1
    try:
        F.assert_track_shape(broken)
    except F.SlotShapeError:
        print("  a motion pair that does not span -1/+1 is refused")
        return
    raise AssertionError("a broken motion pair was accepted")


if __name__ == "__main__":
    for fn in (test_accepts_a_clean_track,
               test_accepts_a_track_with_a_cleared_button_and_trailing_junk,
               test_refuses_a_touch_slot,
               test_refuses_a_track_missing_an_axis_pair):
        print(fn.__name__)
        fn()
    print("\nOK")
