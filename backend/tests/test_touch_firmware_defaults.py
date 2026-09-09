"""On the Touch, EMPTY is the firmware default for exactly four gestures -- both ways.

Live, 2026-09-09, with a Touch docked: fields 0x05-0x08 (one-finger cursor), 0x0b (one-finger
tap) and 0x0c (two-finger tap) read as type 0x07 on every board NayaFlow has written, and the
module still moves the cursor, left-clicks and right-clicks. Pinch/spread (0x11/0x12) are empty
too and do nothing. So:

  read    empty in one of the four decodes to its default and MATCHES an app profile holding
          M1 / M2 / the stock motion pair -- the stock Touch profile is live, and no "(on board)"
          capture claiming the taps are unset is minted;
  write   a binding at the default is written EMPTY so the firmware keeps the cursor; the
          explicit mask / motion records OpenFlow wrote until now give only the coarse motion
          the Tune experiments measured.

Everything else -- a tap bound to a key, a split or inverted axis, pinch/spread, the Track, the
Tune -- is unchanged. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest  # noqa: E402
from openflow_backend.device import module_fields as MF  # noqa: E402
from openflow_backend.device import module_layout as ML  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

T = "TOUCH"
EMPTY = (R.NONE_BEH, b"")
TAP1, TAP2 = "tap:touch:1_finger", "tap:touch:2_fingers"
VERT, HORZ = "vertical:touch:1_finger", "horizontal:touch:1_finger"
H = MF.axis_halves(T)
STOCK_AXES = {VERT: H[VERT]["default"], HORZ: H[HORZ]["default"]}


def _board(override=None):
    """Slot fields as a NayaFlow-written Touch holds them: the four at 0x07, the rest explicit."""
    f = {}
    for gesture, idx in MF.writable_fields(T).items():
        f[idx] = EMPTY if gesture in (TAP1, TAP2) else (R.KEY_PRESS, R.encode_keypress("key", "A"))
    f[MF.mouse_button_fields(T)["tap:touch:3_fingers"]] = (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, 4))
    for gesture, half in H.items():
        for sign in ("-", "+"):
            if gesture in (VERT, HORZ):
                f[half[sign]] = EMPTY
            else:
                f[half[sign]] = (R.TWO_WORD, R.encode_two_word(half["category"], -1 if sign == "-" else 1))
    f.update(override or {})
    return f


def _app(**override):
    """The stock Touch profile's bindings as the app stores them."""
    b = {g: "A" for g in MF.writable_fields(T)}
    b.update({TAP1: "M1", TAP2: "M2", "tap:touch:3_fingers": "M3"})
    for gesture, half in H.items():
        b[gesture] = half["default"]
    b.update(override)
    return b


def test_the_rule_is_exactly_four_gestures_wide():
    assert set(MF.FIRMWARE_DEFAULTS) == {T}, "only the Touch has firmware defaults"
    assert set(MF.FIRMWARE_DEFAULTS[T]) == {TAP1, TAP2, VERT, HORZ}
    for g, code in STOCK_AXES.items():
        assert MF.firmware_default(T, g) == code, "axis default must equal AXIS_HALVES default"
    assert MF.firmware_default(T, "pinch:touch:2_fingers") is None
    assert MF.firmware_default("TRACK", "tap:track:button_1") is None
    print("  four Touch gestures; pinch/spread and the other modules untouched")


def test_a_stock_touch_profile_matches_a_nayaflow_written_slot():
    gestures, differs = rest._compare(T, _board(), _app())
    assert differs == 0, [g for g in gestures if g["differs"]]
    fw = {(g["gesture"], g.get("half")) for g in gestures if g.get("firmwareDefault")}
    assert fw == {(TAP1, None), (TAP2, None), (VERT, "-"), (VERT, "+"), (HORZ, "-"), (HORZ, "+")}
    by = {(g["gesture"], g.get("half")): g["device"] for g in gestures}
    assert by[(TAP1, None)] == "M1" and by[(TAP2, None)] == "M2"
    assert by[(VERT, "-")] == "MOUSE_DOWN" and by[(HORZ, "+")] == "MOUSE_RIGHT"
    print("  empty taps and one-finger axes read as M1 / M2 / the stock motion -> 0 differences")


def test_an_explicit_record_on_the_board_still_matches_the_default():
    """A board OpenFlow wrote before 2026-09-09 carries mask 1 / mask 2 and motion records."""
    idx1, idx2 = MF.mouse_button_fields(T)[TAP1], MF.mouse_button_fields(T)[TAP2]
    explicit = {idx1: (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, 1)),
                idx2: (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, 2))}
    for gesture in (VERT, HORZ):
        for sign in ("-", "+"):
            explicit[H[gesture][sign]] = (R.TWO_WORD, R.encode_two_word(H[gesture]["category"],
                                                                        -1 if sign == "-" else 1))
    _g, differs = rest._compare(T, _board(explicit), _app())
    assert differs == 0
    print("  explicit M1 / M2 / motion records compare equal to the same defaults")


def test_a_tap_bound_to_a_key_still_differs_from_an_empty_field():
    _g, differs = rest._compare(T, _board(), _app(**{TAP1: "B"}))
    assert differs == 1
    print("  app wants B on the one-finger tap, board is at the default -> 1 difference")


def test_an_unbound_app_tap_counts_as_the_default():
    """Nothing else is expressible: an empty field left-clicks whatever the app says."""
    app = _app()
    del app[TAP1]
    _g, differs = rest._compare(T, _board(), app)
    assert differs == 0
    print("  unbound in the app + empty on the board -> no difference")


def test_overlay_writes_the_default_taps_empty_and_a_key_explicitly():
    template = _board()
    idx1, idx2 = MF.mouse_button_fields(T)[TAP1], MF.mouse_button_fields(T)[TAP2]
    out = ML.overlay(template, T, {TAP1: "M1", TAP2: "M2"})
    assert out[idx1] == EMPTY and out[idx2] == EMPTY
    out = ML.overlay(template, T, {TAP1: "B", TAP2: "M3"})
    assert out[idx1] == (R.KEY_PRESS, R.encode_keypress("key", "B"))
    assert out[idx2] == (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, 4))
    print("  M1 / M2 -> empty; B -> keypress; M3 -> explicit mask")


def test_overlay_writes_the_default_axes_empty_and_a_split_or_invert_explicitly():
    at_default = {"minus": None, "plus": None, "invert": False}
    assert ML.encode_axis(T, VERT, at_default) == {H[VERT]["-"]: EMPTY, H[VERT]["+"]: EMPTY}
    assert ML.encode_axis(T, HORZ, at_default) == {H[HORZ]["-"]: EMPTY, H[HORZ]["+"]: EMPTY}
    inverted = ML.encode_axis(T, VERT, dict(at_default, invert=True))
    assert inverted[H[VERT]["-"]] == (R.TWO_WORD, R.encode_two_word(1, 1)), "inverted is spelled out"
    split = ML.encode_axis(T, HORZ, dict(at_default, plus="A"))
    assert split[H[HORZ]["+"]] == (R.KEY_PRESS, R.encode_keypress("key", "A"))
    assert split[H[HORZ]["-"]][0] == R.TWO_WORD, "the other half keeps its motion record"
    # Two-finger scroll is stored on the device and stays explicit.
    scroll = ML.encode_axis(T, "vertical:touch:2_fingers", at_default)
    assert all(rec[0] == R.TWO_WORD for rec in scroll.values())
    print("  one-finger axes at default -> empty; invert / split / two-finger scroll -> explicit")


def test_the_track_is_untouched():
    at_default = {"minus": None, "plus": None, "invert": False}
    for gesture in MF.axis_halves("TRACK"):
        recs = ML.encode_axis("TRACK", gesture, at_default)
        assert all(rec[0] == R.TWO_WORD for rec in recs.values()), gesture
    idx = MF.mouse_button_fields("TRACK")["tap:track:button_1"]
    assert ML.overlay({}, "TRACK", {"tap:track:button_1": "M1"})[idx] == (
        R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, 1))
    print("  Track axes and buttons are still written explicitly")


if __name__ == "__main__":
    for fn in (test_the_rule_is_exactly_four_gestures_wide,
               test_a_stock_touch_profile_matches_a_nayaflow_written_slot,
               test_an_explicit_record_on_the_board_still_matches_the_default,
               test_a_tap_bound_to_a_key_still_differs_from_an_empty_field,
               test_an_unbound_app_tap_counts_as_the_default,
               test_overlay_writes_the_default_taps_empty_and_a_key_explicitly,
               test_overlay_writes_the_default_axes_empty_and_a_split_or_invert_explicitly,
               test_the_track_is_untouched):
        print(fn.__name__)
        fn()
    print("\nOK")
