"""A split half can hold a single motion direction, not only a key.

Gap found 2026-09-11: split the Touch's two-finger horizontal axis and neither half could be
given "scroll left" or "scroll right" -- the palette only offered the pair, and the encoder
turned any non-key code on a half into nothing. The device form was there all along: each
half of a stock pair is a two-word record (category, +/-1), and the eight single directions
are exactly those eight records. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest                                # noqa: E402
from openflow_backend.device import module_fields as MF               # noqa: E402
from openflow_backend.device import module_layout as ML               # noqa: E402
from openflow_backend.device import remap as R                        # noqa: E402

T = "TOUCH"
H = "horizontal:touch:2_fingers"        # fields 0x0f (-) / 0x10 (+), category 6
V = "vertical:touch:2_fingers"          # fields 0x0d (-) / 0x0e (+), category 4


def test_every_direction_is_one_half_of_a_stock_pair():
    assert MF.MOTION_DIRECTIONS == {
        "SCROLL_UP": (4, -1), "SCROLL_DOWN": (4, 1),
        "SCROLL_LEFT": (6, -1), "SCROLL_RIGHT": (6, 1),
        "MOUSE_LEFT": (0, -1), "MOUSE_RIGHT": (0, 1),
        "MOUSE_DOWN": (1, -1), "MOUSE_UP": (1, 1),
        # The zoom axis behind pinch & spread, proved on hardware 2026-09-18.
        "ZOOM_OUT": (8, -1), "ZOOM_IN": (8, 1),
    }
    assert MF.MOTION_NAMES[(6, -1)] == "SCROLL_LEFT"


def test_a_direction_on_a_half_is_the_two_word_record_with_its_own_category():
    halves = MF.axis_halves(T)[H]
    # scroll left kept on the minus half explicitly, a key on the plus half
    out = ML.encode_axis(T, H, {"minus": "SCROLL_LEFT", "plus": "F17", "invert": False})
    assert out[halves["-"]] == (R.TWO_WORD, R.encode_two_word(6, -1))
    assert out[halves["+"]][0] == R.KEY_PRESS
    # a VERTICAL scroll on the horizontal axis: the record carries category 4 in a category-6 field
    out = ML.encode_axis(T, H, {"minus": "SCROLL_UP", "plus": "SCROLL_DOWN", "invert": False})
    assert out[halves["-"]] == (R.TWO_WORD, R.encode_two_word(4, -1))
    assert out[halves["+"]] == (R.TWO_WORD, R.encode_two_word(4, 1))


def test_an_explicit_stock_direction_writes_the_same_bytes_as_no_split():
    """Choosing "scroll left" for the minus half is byte-identical to leaving it as motion."""
    halves = MF.axis_halves(T)[H]
    explicit = ML.encode_axis(T, H, {"minus": "SCROLL_LEFT", "plus": None, "invert": False})
    implicit = ML.encode_axis(T, H, {"minus": None, "plus": None, "invert": False})
    assert explicit[halves["-"]] == implicit[halves["-"]]


def test_the_reader_names_a_foreign_category_by_the_record():
    halves = MF.axis_halves(T)[H]
    assert MF.motion_name(T, halves["-"], 6, -1) == "SCROLL_LEFT", "the field's own axis, as before"
    assert MF.motion_name(T, halves["-"], 4, -1) == "SCROLL_UP", "a vertical scroll in the horizontal field"
    assert MF.motion_name(T, halves["+"], 1, 1) == "MOUSE_UP"
    assert MF.motion_name(T, halves["+"], 9, 1) is None, "an unknown category stays unnamed"


def test_the_compare_agrees_with_the_app_row_for_a_direction_on_a_half():
    halves = MF.axis_halves(T)[H]
    vh = MF.axis_halves(T)[V]
    fields = {
        halves["-"]: (R.TWO_WORD, R.encode_two_word(4, -1)),     # SCROLL_UP on the horizontal minus half
        halves["+"]: (R.TWO_WORD, R.encode_two_word(6, 1)),      # stock scroll right
        vh["-"]: (R.TWO_WORD, R.encode_two_word(4, -1)),
        vh["+"]: (R.TWO_WORD, R.encode_two_word(4, 1)),
    }
    # Every axis the module has needs a row, or the compare answers for the missing one
    # with its stock motion and reports a board that holds nothing as adrift. The Touch
    # gained a third 2-finger axis (pinch & spread) on 2026-09-18.
    app = {H: "mouse - SCROLL_LEFT - SCROLL_RIGHT", (H, "-"): "SCROLL_UP",
           V: "mouse - SCROLL_UP - SCROLL_DOWN",
           "pinch&spread:touch:2_fingers": ""}
    rows, differs = rest._compare(T, fields, app)
    by = {(r["gesture"], r.get("half")): r for r in rows}
    assert by[(H, "-")]["device"] == "SCROLL_UP" and by[(H, "-")]["differs"] is False
    assert by[(H, "+")]["device"] == "SCROLL_RIGHT" and by[(H, "+")]["differs"] is False
    assert differs == 0


def test_buttons_and_keys_on_a_half_are_unchanged():
    assert ML._encode_gesture(0x0F, "M1") == (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, 1))
    assert ML._encode_gesture(0x0F, "F17")[0] == R.KEY_PRESS
