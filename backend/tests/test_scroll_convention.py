"""The scroll direction convention: which sign a named vertical scroll carries on the wire.

NayaFlow's direction names are finger directions under macOS natural scrolling: its "Scroll up"
is (category 4, selector -1), and on a Windows host that record scrolls the page DOWN (measured
on the owner's Touch 2026-09-16, SCRUM-23). So under the Windows convention the encoder writes a
named vertical scroll with the opposite sign and the reader names the board's records the same
way; the default keeps NayaFlow's bytes. Only category 4 flips. The convention is a property of
each MODULE PROFILE (a module_settings row), so one keyboard can carry a Mac profile and a PC
profile side by side. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest                                        # noqa: E402
from openflow_backend.db import module_profiles as mp, userdata as ud       # noqa: E402
from openflow_backend.device import module_fields as MF, module_layout as ML, remap as R  # noqa: E402
import test_module_capture as mc                                             # noqa: E402

VERT = "vertical:tune:1_finger"       # 0x0a (-), 0x0b (+), category 4
HORZ = "horizontal:tune:1_finger"     # 0x0c (-), 0x0d (+), category 6


def _rec(idx, out):
    return R.decode_two_word(out[idx][1])


def test_only_vertical_scroll_flips_and_only_on_windows():
    assert MF.convention_sign(4, -1, "windows") == 1 and MF.convention_sign(4, 1, "windows") == -1
    for cat in (0, 1, 6):
        assert MF.convention_sign(cat, -1, "windows") == -1, f"category {cat} must not flip"
    for conv in (None, "mac"):
        assert MF.convention_sign(4, -1, conv) == -1
    print("  category 4 flips under windows; pointer and horizontal never; mac is identity")


def test_the_default_writes_nayaflows_bytes():
    out = ML.encode_axis("TUNE", VERT, {"minus": None, "plus": None, "invert": False})
    assert _rec(0x0A, out) == (4, -1) and _rec(0x0B, out) == (4, 1)
    same = ML.encode_axis("TUNE", VERT, {"minus": None, "plus": None, "invert": False}, "mac")
    assert same == out
    print("  no convention / mac: the stock (4,-1)/(4,+1) pair, byte for byte")


def test_windows_swaps_the_vertical_pair_and_leaves_horizontal_alone():
    out = ML.encode_axis("TUNE", VERT, {"minus": None, "plus": None, "invert": False}, "windows")
    assert _rec(0x0A, out) == (4, 1) and _rec(0x0B, out) == (4, -1)
    h = ML.encode_axis("TUNE", HORZ, {"minus": None, "plus": None, "invert": False}, "windows")
    assert _rec(0x0C, h) == (6, -1) and _rec(0x0D, h) == (6, 1), "horizontal is not measured; unchanged"
    # invert composes: inverted on Windows is the stock bytes again.
    inv = ML.encode_axis("TUNE", VERT, {"minus": None, "plus": None, "invert": True}, "windows")
    assert _rec(0x0A, inv) == (4, -1) and _rec(0x0B, inv) == (4, 1)
    print("  windows: vertical pair swapped, horizontal untouched, invert composes")


def test_a_single_direction_on_a_split_half_follows_the_convention():
    up_mac = ML._encode_gesture(0x0F, "SCROLL_UP")
    up_win = ML._encode_gesture(0x0F, "SCROLL_UP", "windows")
    assert R.decode_two_word(up_mac[1]) == (4, -1)
    assert R.decode_two_word(up_win[1]) == (4, 1), "Scroll up on Windows is wheel-up: (4, +1)"
    left = ML._encode_gesture(0x0F, "SCROLL_LEFT", "windows")
    assert R.decode_two_word(left[1]) == (6, -1)
    print("  SCROLL_UP is (4,-1) for mac and (4,+1) for windows; SCROLL_LEFT unchanged")


def test_reading_back_names_the_record_the_same_way_it_was_written():
    for conv in (None, "mac", "windows"):
        for name in ("SCROLL_UP", "SCROLL_DOWN", "SCROLL_LEFT", "SCROLL_RIGHT",
                     "MOUSE_LEFT", "MOUSE_RIGHT", "MOUSE_UP", "MOUSE_DOWN"):
            typ, val = ML._encode_gesture(0x0F, name, conv)
            cat, sel = R.decode_two_word(val)
            assert MF.motion_name("TOUCH", 0x0F, cat, sel, conv) == name, (conv, name)
    # A NayaFlow-written board (stock bytes) read on Windows: the swipe-up half scrolls DOWN.
    assert MF.motion_name("TUNE", 0x0A, 4, -1, "windows") == "SCROLL_DOWN"
    assert MF.motion_name("TUNE", 0x0A, 4, -1, "mac") == "SCROLL_UP"
    print("  encode -> decode is the identity under every convention; stock bytes read as Windows sees them")


def test_the_drift_compare_uses_the_same_convention():
    """The app's stock pair against a NayaFlow-written board: no drift under mac; under Windows
    the board's vertical axis reads as the opposite directions, and the app's invert flag is
    what makes it match again."""
    fields = {0x0A: (R.TWO_WORD, R.encode_two_word(4, -1)), 0x0B: (R.TWO_WORD, R.encode_two_word(4, 1))}
    app = {VERT: "mouse - SCROLL_UP - SCROLL_DOWN"}

    def vertical_differs(bindings, conv):
        rows, _n = rest._compare("TUNE", fields, bindings, conv)
        return sum(1 for r in rows if r["gesture"] == VERT and r["differs"])

    assert vertical_differs(app, "mac") == 0
    assert vertical_differs(app, "windows") == 2, "stock bytes are the wrong way round on Windows"
    assert vertical_differs({**app, (VERT, "invert"): True}, "windows") == 0
    print("  compare: mac matches the stock board; windows sees it inverted; invert reconciles")


def test_a_profile_carries_its_own_convention_and_defaults_to_mac():
    assert MF.convention_of(None) == "mac" and MF.convention_of({}) == "mac"
    assert MF.convention_of({"scroll_speed": "50"}) == "mac"
    assert MF.convention_of({MF.SCROLL_CONVENTION_ID: MF.SCROLL_CONVENTION_WINDOWS_LABEL}) == "windows"
    assert MF.convention_of({MF.SCROLL_CONVENTION_ID: "windows"}) == "windows"
    assert MF.convention_of({MF.SCROLL_CONVENTION_ID: MF.SCROLL_CONVENTION_MAC_LABEL}) == "mac"
    # Offered on every module type's settings tab, never as a device field.
    for mtype in ("TOUCH", "TRACK", "TUNE"):
        f = next(f for f in ud.SETTINGS_SCHEMA[mtype] if f["id"] == MF.SCROLL_CONVENTION_ID)
        assert f["kind"] == "select" and f["options"] == [MF.SCROLL_CONVENTION_MAC_LABEL,
                                                          MF.SCROLL_CONVENTION_WINDOWS_LABEL]
        assert not MF.setting_is_writable(mtype, MF.SCROLL_CONVENTION_ID), "not a device field"
    print("  convention_of: default mac, the stored label maps to windows; on every type's tab")


def test_a_capture_inherits_its_templates_convention():
    """The capture's names were decoded under the template's convention, so it must carry it."""
    drifted = dict(mc._DEVICE, **{"tap:track:button_1": "M2"})
    conn = mc._db(drifted)
    conn.execute("INSERT INTO module_settings (module_config_id, correlation_id, value, type, "
                 "updated_at, created_at) VALUES (?,?,?,?,'','')",
                 (mc.UUID, MF.SCROLL_CONVENTION_ID, MF.SCROLL_CONVENTION_WINDOWS_LABEL, "app"))
    conn.commit()
    with mock.patch.object(rest, "db_connect", lambda: mc.KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: mc.KeepOpen(conn)):
        out = rest._module_diff(mc._read(), None)
    cap = out["captured"][0]["id"]
    row = conn.execute("SELECT value FROM module_settings WHERE module_config_id=? AND correlation_id=?",
                       (cap, MF.SCROLL_CONVENTION_ID)).fetchone()
    assert row is not None and row[0] == MF.SCROLL_CONVENTION_WINDOWS_LABEL
    print("  a capture of a Windows profile is a Windows profile")
