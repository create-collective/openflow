"""Every spelling NayaFlow can put in a key binding encodes, and every record reads back.

Found by the 2026-09-09 coverage probe (tools/action_coverage.py) against NayaFlow's full key
palette. Each case below was a real refusal or a real decode hole:

  * "LGUI + CTRL + F" (NayaFlow's own VS Code preset) -- bare CTRL was an unknown token
  * PAGE_UP / PAGE_DOWN / CAPS_LOCK / SCROLL_LOCK / ESCAPE -- what NayaFlow's key recorder stores
  * actionType "combo" -- what that recorder stores a chord AS
  * "LCTRL + LSHIFT" -- a bare modifier list, which NayaFlow's chord grammar allows
  * PIPE2 / TILDE2 -- ZMK's LS(NON_US_BACKSLASH) / LS(NON_US_HASH), in NayaFlow's palette
  * "LCTRL + LSHIFT + C_POWER" -- a consumer key with modifiers lost its modifiers on read
  * "LALT + CLICK" -- modifiers-only record read back as an unknown key
  * a mouse button on a key -- written since C9, never decoded
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402


def _rec(at, code):
    return F._binding_rows_to_record([{"beh": "press", "at": at, "ac": code}], 200, 0, {})


def _round_trip(at, code):
    typ, param = _rec(at, code)
    return kr.translate(typ, param, {})


def test_modifier_token_aliases():
    assert R.encode_keypress("shortcut_alias", "LGUI + CTRL + F") == \
        R.encode_keypress("shortcut_alias", "LGUI + LCTRL + F")
    assert R.encode_keypress("shortcut_alias", "LSHFT + A") == R.encode_keypress("shortcut_alias", "LSHIFT + A")
    assert R.encode_keypress("modifier", "CTRL") == R.encode_keypress("modifier", "LCTRL")
    print("  CTRL / LSHFT spellings encode as LCTRL / LSHIFT")


def test_recorder_code_aliases():
    for alias, canon in (("PAGE_UP", "PG_UP"), ("PAGE_DOWN", "PG_DN"), ("CAPS_LOCK", "CAPSLOCK"),
                         ("SCROLL_LOCK", "SCROLLLOCK"), ("ESCAPE", "ESC"), ("ENTER", "RETURN")):
        assert R.encode_keypress("key", alias) == R.encode_keypress("key", canon), alias
        assert R.encode_keypress("shortcut_alias", f"LGUI + {alias}") == \
            R.encode_keypress("shortcut_alias", f"LGUI + {canon}"), alias
    print("  recorder spellings encode as the palette codes")


def test_combo_is_a_chord():
    assert _rec("combo", "LCTRL + LSHIFT + V") == _rec("shortcut_alias", "LCTRL + LSHIFT + V")
    assert _round_trip("combo", "LCTRL + V") == [("press", "shortcut_alias", "LCTRL + V")]
    print("  a recorded 'combo' writes and reads as a shortcut")


def test_bare_modifier_list_is_modifiers_only():
    assert R.encode_keypress("shortcut_alias", "LCTRL + LSHIFT") == bytes([0, 0, 0, 0x03])
    assert _round_trip("shortcut_alias", "LCTRL + LSHIFT") == [("press", "shortcut_alias", "LCTRL + LSHIFT")]
    print("  'LCTRL + LSHIFT' -> 00000003 -> 'LCTRL + LSHIFT'")


def test_click_chord_keeps_its_modifier_on_the_wire():
    assert R.encode_keypress("shortcut_alias", "LALT + CLICK") == bytes.fromhex("00000004")   # captured
    assert _round_trip("shortcut_alias", "LALT + CLICK") == [("press", "shortcut_alias", "LALT")]
    print("  'LALT + CLICK' -> the captured 00000004 -> reads back as the modifier it holds")


def test_pipe2_and_tilde2_are_shifted_non_us_keys():
    assert R.encode_keypress("key", "PIPE2") == bytes([0x64, 0x00, 0x07, 0x02])
    assert R.encode_keypress("key", "TILDE2") == bytes([0x32, 0x00, 0x07, 0x02])
    assert _round_trip("key", "PIPE2") == [("press", "key", "PIPE2")]
    assert _round_trip("key", "TILDE2") == [("press", "key", "TILDE2")]
    print("  PIPE2 = Shift + NON_US_BACKSLASH, TILDE2 = Shift + NON_US_HASH, both round-trip")


def test_consumer_key_with_modifiers_round_trips():
    typ, param = _rec("shortcut_alias", "LCTRL + LSHIFT + C_POWER")
    assert param == bytes([0x30, 0x00, 0x0C, 0x03])
    assert kr.translate(typ, param, {}) == [("press", "shortcut_alias", "LCTRL + LSHIFT + C_POWER")]
    print("  'LCTRL + LSHIFT + C_POWER' keeps its modifiers through a read")


def test_mouse_button_on_a_key_reads_back():
    for code, mask in R.MOUSE_MASK.items():
        typ, param = _rec("mouse", code)
        assert typ == R.TWO_WORD
        assert kr.translate(typ, param, {}) == [("press", "mouse", code)], code
    unknown = kr.translate(kr.MOUSE_TWO_WORD, R.encode_two_word(3, 64), {})
    assert unknown[0][1] == "mouse" and str(unknown[0][2]).startswith("RAW_")
    print("  M1-M5 on a key decode; an unknown mask stays RAW")


def test_international_keys_encode():
    for n in range(1, 10):
        assert R.encode_keypress("key", f"INT{n}") == bytes([0x87 + n - 1, 0, 7, 0]), n
        assert R.encode_keypress("key", f"LANG{n}") == bytes([0x90 + n - 1, 0, 7, 0]), n
    print("  INT1-9 / LANG1-9 are HID 0x87-0x8f / 0x90-0x98")


if __name__ == "__main__":
    for fn in (test_modifier_token_aliases, test_recorder_code_aliases, test_combo_is_a_chord,
               test_bare_modifier_list_is_modifiers_only, test_click_chord_keeps_its_modifier_on_the_wire,
               test_pipe2_and_tilde2_are_shifted_non_us_keys, test_consumer_key_with_modifiers_round_trips,
               test_mouse_button_on_a_key_reads_back, test_international_keys_encode):
        print(fn.__name__)
        fn()
    print("\nOK")
