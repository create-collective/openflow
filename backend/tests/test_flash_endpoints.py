"""Offline coverage for the flash-preview + module-gestures endpoint logic.

Exercises the functions the routes call (not the HTTP layer): the gesture dropdown data and
the dry flash-preview built from a real DB snapshot committed in the repo. No hardware, no writes.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import gesture_presets as gp  # noqa: E402
from openflow_backend.device import module_fields as mf  # noqa: E402

SNAPSHOT = _REPO / "device" / "userdata-snapshot" / "user-data-2026-08-28.db"


def test_module_gesture_dropdowns() -> None:
    tune = gp.gestures_for("TUNE")
    # 13, including the dial directions at 0x22/0x23. The earlier retraction to 11 rested
    # on "Touch carries the same pair and has no dial" -- but that Touch map was probed at
    # slot 1, a 36-field hybrid, and a real Touch config is 31 fields, so everything above
    # 0x1e there was an orphaned tail rather than Touch schema.
    assert len(tune) == 13, f"expected 13 Tune gestures, got {len(tune)}"
    for g in tune:
        assert g["allow_custom"] is True and g["presets"], "every gesture allows custom + has presets"
        assert isinstance(g["field"], int)
    # a media preset the encoder can actually emit
    codes = {p["action_code"] for p in gp.presets_for("TUNE")}
    assert {"C_PLAY_PAUSE", "C_MUTE", "C_VOL_UP"} <= codes
    # TRACK has a field map but no writable gesture fields -> empty list (UI shows a note)
    assert gp.gestures_for("TRACK") == [] and mf.field_map("TRACK")
    print(f"Dropdowns OK: TUNE {len(tune)} gestures x {len(gp.presets_for('TUNE'))} presets + custom; "
          f"TRACK empty (axis-only)")


def test_flash_preview_from_db() -> None:
    conn = sqlite3.connect(str(SNAPSHOT))
    conn.row_factory = sqlite3.Row
    try:
        desired = F.desired_from_db(conn)
    finally:
        conn.close()
    result = F.flash(desired, dry_run=True, full=True)
    assert result["dry_run"] is True and result["frames"], "preview must render frames, dry"
    s = result["summary"]
    assert s["total_frames"] > 0 and s["ops"], "empty preview"
    # all layer/led writes go to the central left half
    assert s["dest"] == "0x50"
    labels = [op["label"] for op in s["ops"]]
    assert any(l.startswith("layer") for l in labels), "no layer writes in preview"
    print(f"Preview OK: {len(s['ops'])} ops, {s['total_frames']} frames, {s['total_bytes']} bytes, dry")


if __name__ == "__main__":
    test_module_gesture_dropdowns()
    test_flash_preview_from_db()
