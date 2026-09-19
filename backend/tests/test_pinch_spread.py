"""Pinch & spread is a zoom AXIS, not one gesture and not a dead slot (SCRUM-84).

Our code used to assert that pinch and spread were a single gesture on this hardware, and the
field map said the two slots behind them "are empty and do nothing". Both were wrong, and the
second is why nobody ever tried: the fields are empty on every NayaFlow-written board because
NayaFlow never writes them, not because the firmware ignores them.

What settled it, 2026-09-18:
  * NayaCore names the fields itself in its own pre-flash profile dump: TUNE:PINCH_OUT_2 (0x15).
  * Its category enum lists MOUSE_HORIZONTAL, MOUSE_VERTICAL, MOUSE_STATIC, MOUSE_BUTTONS,
    MOUSE_SCROLL_VERTICAL, STATIC_SCROLL_VERTICAL, MOUSE_SCROLL_HORIZONTAL,
    STATIC_SCROLL_HORIZONTAL, STATIC_ZOOM -- indices 0,1,3,4,6 are exactly the categories we had
    already measured, which makes STATIC_ZOOM category 8.
  * On the owner's board: category 8 in the pair zoomed in and out; two keypresses in the same
    pair typed one letter per direction.

So it behaves exactly like vertical and horizontal: one combined row, two fields, sign is the
direction, and the split control breaks it into halves. No hardware needed for these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import module_actions as MA  # noqa: E402
from openflow_backend.device import module_fields as MF  # noqa: E402
from openflow_backend.device import module_layout as ml  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

ZOOM_CATEGORY = 8

# (module type, combined behavior, pinch field, spread field)
AXES = [
    ("TUNE", "pinch&spread:tune:2_fingers", 0x14, 0x15),
    ("TOUCH", "pinch&spread:touch:2_fingers", 0x11, 0x12),
]


@pytest.mark.parametrize("mtype,behavior,minus,plus", AXES)
def test_the_axis_is_declared_on_the_fields_nayacore_names(mtype, behavior, minus, plus):
    h = MF.axis_halves(mtype)[behavior]
    assert (h["-"], h["+"]) == (minus, plus)
    assert h["category"] == ZOOM_CATEGORY
    assert h["default"] == "mouse - ZOOM_OUT - ZOOM_IN"


@pytest.mark.parametrize("mtype,behavior,minus,plus", AXES)
def test_it_is_splittable_like_every_other_axis(mtype, behavior, minus, plus):
    """The whole point: the existing split control has to pick it up with no special casing."""
    assert behavior in MF.splittable_axes(mtype)
    assert MF.gesture_kind(mtype, behavior) == "axis"


@pytest.mark.parametrize("mtype,behavior,minus,plus", AXES)
def test_each_half_decodes_to_its_own_direction(mtype, behavior, minus, plus):
    """A read must name what it finds, and minus must be the zoom-OUT half."""
    assert MF.motion_name(mtype, minus, ZOOM_CATEGORY, -1) == "ZOOM_OUT"
    assert MF.motion_name(mtype, plus, ZOOM_CATEGORY, +1) == "ZOOM_IN"


def test_the_two_directions_are_derived_not_declared_twice():
    d = MF._motion_directions()
    assert d["ZOOM_OUT"] == (ZOOM_CATEGORY, -1)
    assert d["ZOOM_IN"] == (ZOOM_CATEGORY, +1)


def test_zoom_is_not_flipped_per_os():
    """Scroll direction follows the user's OS convention. Zoom does not, on either platform.

    Asserted against convention_sign rather than against the set it reads, so the guarantee
    survives someone adding a category to FLIPPED_ON_WINDOWS.
    """
    for convention in (MF.CONVENTION_MAC, MF.CONVENTION_WINDOWS, None):
        for sign in (-1, +1):
            assert MF.convention_sign(ZOOM_CATEGORY, sign, convention) == sign


def test_the_track_has_no_zoom_axis():
    """A Track has no touch surface, and its spare fields are not a pinch pair."""
    assert not [g for g in MF.axis_halves("TRACK") if g.startswith("pinch")]


@pytest.mark.parametrize("mtype,behavior,minus,plus", AXES)
def test_combined_writes_one_category_into_both_halves(mtype, behavior, minus, plus):
    """Combined means ONE motion category split by sign, which is what made it zoom."""
    tmpl = {minus: (R.NONE_BEH, b""), plus: (R.NONE_BEH, b"")}
    cfg = ml.overlay(tmpl, mtype, {}, axes={behavior: {"minus": None, "plus": None,
                                                       "invert": False}})
    assert cfg[minus] == (R.TWO_WORD, R.encode_two_word(ZOOM_CATEGORY, -1))
    assert cfg[plus] == (R.TWO_WORD, R.encode_two_word(ZOOM_CATEGORY, +1))


@pytest.mark.parametrize("mtype,behavior,minus,plus", AXES)
def test_split_writes_two_independent_keypresses(mtype, behavior, minus, plus):
    """And split means each field holds its own record, which is what typed one letter each."""
    tmpl = {minus: (R.NONE_BEH, b""), plus: (R.NONE_BEH, b"")}
    cfg = ml.overlay(tmpl, mtype, {}, axes={behavior: {"minus": "A", "plus": "B",
                                                       "invert": False}})
    assert cfg[minus] == (R.KEY_PRESS, R.encode_keypress("key", "A"))
    assert cfg[plus] == (R.KEY_PRESS, R.encode_keypress("key", "B"))


def test_zoom_is_offered_as_an_action():
    """NayaFlow's combined control accepted only `value` actions and its catalogue had no zoom,
    which is the reason its own pinch & spread could never be bound to anything useful."""
    zoom = [a for a in MA.MODULE_ACTIONS if a["code"] == "mouse - ZOOM_OUT - ZOOM_IN"]
    assert len(zoom) == 1
    assert zoom[0]["actionType"] == "value"


@pytest.mark.parametrize("mtype,behavior,minus,plus", AXES)
def test_the_field_map_no_longer_calls_the_slots_dead(mtype, behavior, minus, plus):
    fm = json.loads((_BACKEND / "openflow_backend/device/module_field_map.json")
                    .read_text(encoding="utf-8"))
    for field in (minus, plus):
        entry = fm[mtype]["fields"]["0x%02x" % field]
        assert entry["kind"] == "axis"
        assert entry["axis"] == ZOOM_CATEGORY
        assert entry["gesture"] == behavior


def test_the_tune_one_finger_labels_match_the_table_that_drives_writes():
    """The field map's own gesture labels for 0x0a-0x0d contradicted AXIS_HALVES, which is what
    reads and writes actually use. NayaCore's dump settles it: UP_1 is 0x0a, so 0x0a/0x0b are
    the VERTICAL pair. Cosmetic, but a label that disagrees with the encoder is a trap."""
    fm = json.loads((_BACKEND / "openflow_backend/device/module_field_map.json")
                    .read_text(encoding="utf-8"))
    halves = MF.axis_halves("TUNE")
    for behavior, h in halves.items():
        for sign in ("-", "+"):
            entry = fm["TUNE"]["fields"].get("0x%02x" % h[sign], {})
            if entry.get("gesture"):
                assert entry["gesture"] == behavior, (
                    "field 0x%02x is labelled %s but AXIS_HALVES writes %s there"
                    % (h[sign], entry["gesture"], behavior))


def test_the_old_one_gesture_rows_are_retired(tmp_path):
    """The behavior the old model invented pointed at no field, so an unbound leftover is dropped
    rather than left to render as a second, unbindable Pinch line."""
    import sqlite3
    from openflow_backend.db import module_profiles as mp

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE module_bindings (behavior TEXT, action_code TEXT)")
    conn.executemany("INSERT INTO module_bindings VALUES (?,?)", [
        ("pinch:touch:2_fingers", ""),
        ("pinch:tune:2_fingers", None),
        ("pinch&spread:touch:2_fingers", "mouse - ZOOM_OUT - ZOOM_IN"),
        ("tap:tune:1_finger", "C_MUTE"),
        ("pinch:tune:2_fingers", "A"),          # a BOUND leftover: the user's, so it stays
    ])
    assert mp.drop_retired_pinch_rows(conn) == 2
    left = {(r["behavior"], r["action_code"]) for r in
            conn.execute("SELECT behavior, action_code FROM module_bindings")}
    assert ("pinch:tune:2_fingers", "A") in left, "a bound row is never deleted to tidy a model"
    assert ("pinch&spread:touch:2_fingers", "mouse - ZOOM_OUT - ZOOM_IN") in left
    assert ("tap:tune:1_finger", "C_MUTE") in left
    assert len(left) == 3


def test_the_migration_tolerates_a_database_without_the_table():
    """init_db also runs over an imported NayaFlow or beta database, which may predate
    module_bindings entirely (tests/test_backup_import_migrates.py)."""
    import sqlite3
    from openflow_backend.db import module_profiles as mp
    conn = sqlite3.connect(":memory:")
    assert mp.drop_retired_pinch_rows(conn) == 0
