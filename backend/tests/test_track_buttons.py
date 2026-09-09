"""The Track button field map, pinned to the live write + read that proved it.

1. Our encoder re-encodes all three captured WRITE_MODULE_CONFIG_DATA payloads from the
   2026-09-02 Track Left flash byte-exactly (slot 4 = Track, 3 = Touch, 1 = a 1-field
   sparse write) -- so the record format is settled for module configs, not just layers.
2. The four axis-3 fields 0x0b-0x0e decode to each Track profile's button_1..4 mouse
   buttons, in field order, for BOTH orientations. That is what makes them buttons rather
   than a fixed schema block.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
# Walk up to whichever directory holds the shared device captures. NayaOS nests this tree
# under openflow/ while this repository has it at the root, so a hardcoded parent index
# only works in one of them.
_REPO = next(p for p in _BACKEND.parents if (p / "device").is_dir())
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import module_fields as mf  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

WRITES = json.loads((_REPO / "device" / "out" / "track-swap-writes.json").read_text())
MASK = {1: "M1", 2: "M2", 4: "M3", 8: "M4"}
# Each profile's button_1..4, from the NayaFlow user data.
TRACK_RIGHT = ["M4", "M2", "M3", "M1"]   # the earlier read, stored at slot 3
TRACK_LEFT = ["M1", "M3", "M2", "M4"]    # what this flash wrote, stored at slot 4


def test_captured_writes_reencode_exactly():
    for slot in ("1", "3", "4"):
        captured = bytes.fromhex(WRITES[slot])
        recs = list(kr.parse_records(captured[1:]))
        rebuilt = R.encode_module_config(int(slot), [R.encode_module_field(f, v, t) for f, t, v in recs])
        assert rebuilt == captured, f"slot {slot} re-encode differs from the captured write"
    # the 4-byte write to slot 1 is a single field -- module writes can be sparse
    assert len(list(kr.parse_records(bytes.fromhex(WRITES["1"])[1:]))) == 1
    print("  slots 1/3/4 re-encode byte-exactly; sparse single-field write confirmed")


def test_track_buttons_decode_to_the_flashed_profile():
    captured = bytes.fromhex(WRITES["4"])
    recs = {f: (t, v) for f, t, v in kr.parse_records(captured[1:])}
    got = []
    for field in (0x0B, 0x0C, 0x0D, 0x0E):
        typ, val = recs[field]
        axis = int.from_bytes(val[:4], "little")
        mask = int.from_bytes(val[4:8], "little", signed=True)
        assert axis == 3, f"field {field:#04x} is not an axis-3 record"
        got.append(MASK[mask])
    assert got == TRACK_LEFT, f"captured Track Left write decodes to {got}, expected {TRACK_LEFT}"
    assert got != TRACK_RIGHT, "the two orientations must differ, else the order is schema-fixed"
    print(f"  slot 4 buttons decode to {got} == Naya Track Left (Right was {TRACK_RIGHT})")


def test_field_map_agrees():
    fields = mf.field_map("TRACK")
    for i, k in enumerate(("0x0b", "0x0c", "0x0d", "0x0e"), start=1):
        f = fields[k]
        assert f["kind"] == "mouse_button" and f["gesture"] == f"tap:track:button_{i}"
        assert MASK[f["mask"]] == TRACK_LEFT[i - 1]
    # a Track config is 15 fields and carries no keypress gesture fields
    assert len(fields) == 15 and mf.gesture_fields("TRACK") == {}
    print("  field map matches; Track config is 15 fields, no keypress gestures")


def test_only_the_buttons_differ_between_orientations():
    """The strongest evidence that category 3 is buttons and not ball direction: swapping
    Track Right -> Track Left changes ONLY the four category-3 values, and permutes them
    rather than negating them. The motion axes (categories 0/1/4) are byte-identical, so
    whatever inverts the ball physically is not stored in this config."""
    recs = {f: v for f, t, v in kr.parse_records(bytes.fromhex(WRITES["4"])[1:]) if t == 0x0F}
    motion = {f: v for f, v in recs.items() if f <= 0x0A}
    # from the earlier Track Right read (module_field_map before the 2026-09-02 update)
    RIGHT_MOTION = {0x05: (1, -1), 0x06: (1, 1), 0x07: (0, -1), 0x08: (0, 1),
                    0x09: (4, 1), 0x0A: (4, -1)}
    for f, v in motion.items():
        cat = int.from_bytes(v[:4], "little")
        direction = int.from_bytes(v[4:], "little", signed=True)
        assert (cat, direction) == RIGHT_MOTION[f], f"motion field {f:#04x} differs between orientations"
    buttons = [int.from_bytes(recs[f][4:], "little", signed=True) for f in (0x0B, 0x0C, 0x0D, 0x0E)]
    assert sorted(buttons) == [1, 2, 4, 8], "category-3 values are not a permutation of the 4 masks"
    assert all(b > 0 for b in buttons), "a button mask is never negative (a direction would be)"
    print("  motion axes identical across orientations; only the 4 button masks permute")


if __name__ == "__main__":
    for fn in (test_captured_writes_reencode_exactly,
               test_track_buttons_decode_to_the_flashed_profile,
               test_field_map_agrees,
               test_only_the_buttons_differ_between_orientations):
        print(fn.__name__)
        fn()
    print("\nOK")


