"""Validate the module gesture field map + gesture write path, offline.

1. The field map's default gesture actions re-encode to the exact bytes the device returned
   for Tune's keypress fields (proves the map + keypress encoder against a real read).
2. module_gesture_write builds a sparse WRITE_MODULE_CONFIG_DATA that re-parses to the intended
   fields, and matches how the captured 1-finger-tap write was framed.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import module_fields as mf  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

# The Tune keypress fields exactly as the device returned them (flash2.pcap slot 4).
TUNE_DEVICE_KEYPRESS = {
    0x08: "2a000700",  # Backspace (user-set 1-finger tap)
    0x0e: "cd000c00",  # C_PLAY_PAUSE
    0x10: "6f000c00",  # C_BRIGHTNESS_INC
    0x11: "70000c00",  # C_BRIGHTNESS_DEC
    0x12: "b4000c00",  # C_REWIND
    0x13: "b3000c00",  # C_FAST_FORWARD
    0x16: "e2000c00",  # C_MUTE
    0x1a: "b6000c00",  # C_PREVIOUS
    0x1b: "b5000c00",  # C_NEXT
    0x22: "e9000c00",  # C_VOL_UP
    0x23: "ea000c00",  # C_VOL_DOWN
}


def test_field_map_reencodes_device_bytes() -> None:
    """Every labeled Tune keypress field's action re-encodes to the device's exact bytes."""
    fmap = mf.field_map("TUNE")
    checked = 0
    for field_hex, info in fmap.items():
        if info.get("kind") != "keypress":
            continue
        field = int(field_hex, 16)
        raw = TUNE_DEVICE_KEYPRESS.get(field)
        if raw is None:
            continue
        at, code = kr.decode_keypress(bytes.fromhex(raw))
        if isinstance(code, kr.Unmapped):
            continue
        assert R.encode_keypress(at, code).hex() == raw, f"field 0x{field:02x} ({code}) re-encode mismatch"
        checked += 1
    assert checked >= 8, f"expected >=8 keypress fields validated, got {checked}"
    print(f"Field map OK: {checked} Tune gesture keypress fields re-encode to the device bytes")


def test_gesture_write_roundtrip() -> None:
    """Rebinding gestures (a preset and a custom key) produces a sparse write that re-parses right."""
    changes = {
        "tap:tune:2_fingers": ("key", "C_MUTE"),      # preset consumer key
        "swipe_up:tune:2_fingers": ("key", "A"),      # custom key bind — like our Backspace
        "swipe_left:tune:3_fingers": ("modifier", "LCTRL"),
    }
    op = F.module_gesture_write(slot=4, module_type="TUNE", changes=changes)
    assert op is not None and op.sub == R.WRITE_MODULE_CONFIG_DATA
    assert op.payload[0] == 4  # slot byte

    gf = mf.gesture_fields("TUNE")
    recs = {f: (t, p) for f, t, p in kr.parse_records(op.payload[1:])}
    assert set(recs) == {gf[g] for g in changes}, "written fields != mapped gesture fields"
    for gesture, (atype, acode) in changes.items():
        typ, param = recs[gf[gesture]]
        assert typ == R.KEY_PRESS and param == R.encode_keypress(atype, acode)

    # frames match the same chunking the captured 1-finger-tap write used (single small frame)
    frames = R.frames_for(0x50, op.sub, op.payload)
    assert len(frames) == 1 and frames[0][3] == 0x00  # byte3 countdown = 0 for a single frame
    print(f"Gesture write OK: {len(changes)} gestures -> fields {sorted(recs)}, "
          f"1 frame, custom + preset + modifier all encoded")


def test_track_has_no_writable_gestures() -> None:
    """Track's read had only axis fields — writing a gesture must fail loudly, not silently."""
    assert mf.gesture_fields("TRACK") == {}, "Track unexpectedly has keypress gesture fields"
    try:
        F.module_gesture_write(slot=3, module_type="TRACK", changes={"tap:track:button_1": ("key", "A")})
        raise AssertionError("expected RemapEncodeError for an unmapped Track gesture")
    except R.RemapEncodeError:
        pass
    print("Track OK: no on-device gesture keypress fields; gesture write refuses (as designed)")


if __name__ == "__main__":
    test_field_map_reencodes_device_bytes()
    test_gesture_write_roundtrip()
    test_track_has_no_writable_gestures()
