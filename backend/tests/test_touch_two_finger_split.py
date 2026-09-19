"""The Touch: two-finger scroll splits per direction; the four firmware gestures are locked.

Decided 2026-09-09 with a Touch docked. NayaFlow's editor splits the Touch's two-finger axes
(two device fields each, 0x0d/0x0e and 0x0f/0x10, the shape the Tune already splits) and locks
its one-finger tap, two-finger tap and one-finger vertical / horizontal -- the four gestures the
module firmware drives while their fields are empty (module_fields.FIRMWARE_DEFAULTS). OpenFlow
had the reverse: no split on the Touch ("no gain") and free rebinding of the locked four. Now:

  * splittable_axes("TOUCH") is exactly the two-finger axes;
  * set_axis_split / set_axis_invert refuse the one-finger axes, set_module_binding refuses the
    locked taps, and get_modules flags them `locked` with the firmware's behaviour;
  * the flash writes a locked field EMPTY whatever an old row holds, and the compare never
    counts a locked gesture as drift.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest  # noqa: E402
from openflow_backend.db import userdata as ud  # noqa: E402
from openflow_backend.device import module_fields as MF  # noqa: E402
from openflow_backend.device import module_layout as ML  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

T = "TOUCH"
# Three 2-finger axes since 2026-09-18: pinch & spread is one too (fields 0x11/0x12, a
# category-8 zoom pair proved on hardware).
TWO = {"horizontal:touch:2_fingers", "vertical:touch:2_fingers",
       "pinch&spread:touch:2_fingers"}
ONE = {"horizontal:touch:1_finger", "vertical:touch:1_finger"}
EMPTY = (R.NONE_BEH, b"")
CID = "touch-1"


def test_only_the_two_finger_axes_are_splittable():
    assert set(MF.splittable_axes(T)) == TWO
    assert set(MF.axis_halves(T)) == TWO | ONE, "the compare still needs every axis"
    assert set(MF.splittable_axes("TUNE")) == set(MF.axis_halves("TUNE"))
    assert set(MF.splittable_axes("TRACK")) == set(MF.axis_halves("TRACK"))
    print("  Touch: 2-finger axes split, 1-finger axes do not; Tune and Track unchanged")


def test_the_locked_set_is_the_firmware_default_set():
    assert MF.FIRMWARE_LOCKED[T] == {"tap:touch:1_finger", "tap:touch:2_fingers"} | ONE
    assert MF.gesture_locked(T, "tap:touch:2_fingers") and not MF.gesture_locked(T, "tap:touch:3_fingers")
    assert not MF.gesture_locked("TRACK", "tap:track:button_1")
    print("  locked = the four firmware-driven gestures, nothing else")


def test_a_split_two_finger_half_writes_a_key_and_keeps_the_other_halfs_motion():
    h = MF.axis_halves(T)["vertical:touch:2_fingers"]
    out = ML.encode_axis(T, "vertical:touch:2_fingers", {"minus": "F17", "plus": None, "invert": False})
    assert out[h["-"]] == (R.KEY_PRESS, R.encode_keypress("key", "F17"))
    assert out[h["+"]] == (R.TWO_WORD, R.encode_two_word(h["category"], 1))
    print("  two fingers up -> F17 as a keypress, two fingers down keeps its scroll record")


def test_a_locked_axis_is_written_empty_even_if_a_row_asks_otherwise():
    h = MF.axis_halves(T)["vertical:touch:1_finger"]
    out = ML.encode_axis(T, "vertical:touch:1_finger", {"minus": "F17", "plus": "F18", "invert": True})
    assert out == {h["-"]: EMPTY, h["+"]: EMPTY}
    idx = MF.mouse_button_fields(T)["tap:touch:1_finger"]
    assert ML.overlay({}, T, {"tap:touch:1_finger": "B"})[idx] == EMPTY
    print("  locked axis and locked tap -> empty on the wire, whatever the rows say")


def test_the_compare_never_counts_a_locked_gesture_as_drift():
    fields = {MF.mouse_button_fields(T)["tap:touch:1_finger"]: EMPTY}
    for gesture, idx in MF.writable_fields(T).items():
        fields.setdefault(idx, EMPTY)
    for gesture, half in MF.axis_halves(T).items():
        for sign in ("-", "+"):
            fields[half[sign]] = EMPTY if gesture in ONE else (R.TWO_WORD, R.encode_two_word(half["category"], -1 if sign == "-" else 1))
    app = {g: None for g in MF.writable_fields(T)}
    app["tap:touch:1_finger"] = "B"                              # an old edit on a locked row
    for gesture, half in MF.axis_halves(T).items():
        app[gesture] = half["default"]
    gestures, differs = rest._compare(T, fields, app)
    locked_rows = [g for g in gestures if g.get("locked")]
    assert len(locked_rows) == 2 + 4, [g["gesture"] for g in locked_rows]
    assert not any(g["differs"] for g in locked_rows)
    assert differs == 0
    print("  the six locked rows (two taps, four half-axes) are flagged and never differ")


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (name TEXT, type TEXT, size INT, order_id INT, icon_id TEXT,
                                     variant TEXT, captured_from TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT, behavior TEXT,
                                      invert INT, threshold INT, direction TEXT, mode INT,
                                      module_config_id TEXT, id TEXT, updated_at TEXT, created_at TEXT);
    """)
    conn.execute("INSERT INTO module_configs (name,type,size,order_id,id,updated_at,created_at) "
                 "VALUES ('Touch',?,0,0,?,'','')", (T, CID))
    conn.execute("INSERT INTO module_bindings (action_code,action_type,behavior,invert,threshold,direction,"
                 "mode,module_config_id,id,updated_at,created_at) VALUES ('M1','mouse','tap:touch:1_finger',"
                 "0,0,'+',0,?,'b-tap1','','')", (CID,))
    conn.commit()
    return conn


def test_the_database_layer_refuses_the_locked_gestures():
    conn = _db()
    with mock.patch.object(ud, "connect", lambda: KeepOpen(conn)):
        for axis in ONE:
            try:
                ud.set_axis_split(CID, axis, "-", "F17")
                raise AssertionError(f"split accepted on {axis}")
            except ValueError as e:
                assert "splittable" in str(e)
            try:
                ud.set_axis_invert(CID, axis, True)
                raise AssertionError(f"invert accepted on {axis}")
            except ValueError as e:
                assert "invertible" in str(e)
        try:
            ud.set_module_binding("b-tap1", "B", "key")
            raise AssertionError("rebinding the one-finger tap was accepted")
        except ValueError as e:
            assert "firmware" in str(e)
        assert conn.execute("SELECT action_code FROM module_bindings WHERE id='b-tap1'").fetchone()[0] == "M1"
        # and the two-finger axis still splits
        ud.set_axis_split(CID, "vertical:touch:2_fingers", "-", "F17")
        got = conn.execute("SELECT action_code, direction FROM module_bindings WHERE behavior='vertical:touch:2_fingers' "
                           "AND direction='-' AND action_code NOT LIKE '% - %'").fetchone()
        assert tuple(got) == ("F17", "-")
    print("  one-finger axes and the tap refuse; two-finger split lands as a per-half row")


if __name__ == "__main__":
    for fn in (test_only_the_two_finger_axes_are_splittable, test_the_locked_set_is_the_firmware_default_set,
               test_a_split_two_finger_half_writes_a_key_and_keeps_the_other_halfs_motion,
               test_a_locked_axis_is_written_empty_even_if_a_row_asks_otherwise,
               test_the_compare_never_counts_a_locked_gesture_as_drift,
               test_the_database_layer_refuses_the_locked_gestures):
        print(fn.__name__)
        fn()
    print("\nOK")


# --- the axis pairing itself, measured -----------------------------------------------------

def test_the_touch_two_finger_axes_are_paired_the_way_the_pad_fires_them():
    """2026-09-10, create-companion census with Ctrl+F13..F16 in the four halves: an up-swipe
    fired the key in 0x0d and a down-swipe 0x0e; left fired 0x0f and right 0x10. The table had
    these two pairs the other way round, exactly the open question the field map recorded."""
    h = MF.axis_halves("TOUCH")
    assert (h["vertical:touch:2_fingers"]["-"], h["vertical:touch:2_fingers"]["+"]) == (0x0D, 0x0E)
    assert (h["horizontal:touch:2_fingers"]["-"], h["horizontal:touch:2_fingers"]["+"]) == (0x0F, 0x10)


def test_scroll_category_means_the_same_axis_on_every_module():
    """The firmware's two scroll categories are not per module: 4 is vertical and 6 is
    horizontal on the Tune (measured 2026-09-04) and on the Touch (2026-09-10). A table that
    gives the same category two different axes on two modules is wrong on one of them."""
    by_cat = {}
    for module in ("TUNE", "TOUCH"):
        for gesture, half in MF.axis_halves(module).items():
            if half["category"] in (4, 6):
                axis = gesture.split(":")[0]
                by_cat.setdefault(half["category"], set()).add(axis)
    assert by_cat == {4: {"vertical"}, 6: {"horizontal"}}, by_cat
