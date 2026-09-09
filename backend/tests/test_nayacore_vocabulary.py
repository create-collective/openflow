"""OpenFlow's key encoder agrees with NayaCore.exe's own parameter tables.

docs/reference/nayacore-action-vocabulary.json was read out of the vendor's serialiser binary
(2026-09-09): a 249-entry table of the 4-byte key_press param (usage, page, mods) in ZMK order,
the 19 LED (argument, subcommand) pairs, the Bluetooth / output / mouse pairs and the modifier
alias table. It is the closest thing to the vendor's source we will ever hold, and the four LED
colours captured from hardware reproduce it byte for byte -- which is what lets the rest of it
stand as evidence. Every key name both sides know must encode to the same bytes. No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = next(p for p in _BACKEND.parents if (p / "docs" / "reference").is_dir())
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

VOCAB = _REPO / "docs" / "reference" / "nayacore-action-vocabulary.json"
CORE = json.loads(VOCAB.read_text(encoding="utf-8"))


def _param(e) -> bytes:
    usage = int(e["usage"], 16)
    return bytes([usage & 0xFF, usage >> 8, int(e["page"], 16), int(e["mods"], 16)])


def test_every_shared_key_name_encodes_to_nayacore_bytes():
    core = {e["nayacore_name_inferred"]: _param(e) for e in CORE["key_param_table"]}
    shared, wrong = 0, []
    for name, want in core.items():
        try:
            got = R.encode_keypress(R.keypress_type(name), name)
        except R.RemapEncodeError:
            continue                          # a NayaCore-only name; not claimed
        shared += 1
        if got != want:
            wrong.append((name, want.hex(), got.hex()))
    assert shared >= 150, f"only {shared} names shared -- the table did not load as expected"
    assert not wrong, f"encodings that differ from NayaCore's table: {wrong}"
    print(f"  {shared} key names encode exactly as NayaCore's table says")


def test_every_nayaflow_palette_key_is_in_nayacore_table():
    """A key NayaFlow offers that NayaCore could not serialise would be a vendor bug; there is
    none, and this is what proves the two JIS keys and the International row are real."""
    # Compared by BYTES, not by name: the table's names are ZMK aliases (INTERNATIONAL_1 where
    # NayaFlow's palette says INT1), and what matters is that the exact param exists in it.
    params = {_param(e) for e in CORE["key_param_table"]}
    for name in ("PIPE2", "TILDE2", "NON_US_HASH", "NON_US_BACKSLASH", "INT1", "INT6", "LANG1", "LANG9",
                 "K_APP", "KP_NUMLOCK", "PAUSE_BREAK", "SCROLLLOCK", "F24", "C_POWER", "C_FAST_FORWARD"):
        assert R.encode_keypress("key", name) in params, name
    print("  the International row, both JIS glyphs and the consumer keys are in the table")


def test_led_colours_are_nayacore_values():
    ours = {code: (b, s, h) for (b, s, h), code in kr.RGB_COLORS.items()}
    seen = 0
    for p in CORE["led_params"]:
        if "hsb" not in p:
            continue
        seen += 1
        h, s, b = p["hsb"]["h"], p["hsb"]["s"], p["hsb"]["b"]
        assert p["argument"] == (b | (s << 8) | (h << 16)), p["name"]
        assert ours.get(p["name"]) == (b, s, h), (p["name"], ours.get(p["name"]))
        # and the encoder packs exactly the vendor's argument
        packed = int.from_bytes(R.encode_rgb_system(p["name"])[4:8], "little")
        assert packed == p["argument"], p["name"]
    assert seen == 9
    print("  all nine LED colours pack to NayaCore's arguments")


def test_led_subcommands_and_effects_match():
    for p in CORE["led_params"]:
        sub, arg = int(p["subcommand"], 16), p["argument"]
        param = R.encode_rgb_system(p["name"])
        assert int.from_bytes(param[:4], "little") == sub, p["name"]
        assert int.from_bytes(param[4:8], "little") == arg, p["name"]
        assert kr.decode_rgb_system(param) == p["name"], p["name"]
    print(f"  all {len(CORE['led_params'])} LED actions encode and decode to the vendor's pairs")


def test_bluetooth_outputs_and_mouse_pairs_match():
    bt = {p["name"]: tuple(p["memory_pair_(arg,cmd)"]) for p in CORE["bluetooth_params"]}
    # memory stores (argument, command); the wire is [command][argument]
    for n in range(1, 5):
        arg, cmd = bt[f"BT_DEVICE_{n}"]
        assert R.encode_twoparam(cmd, arg) == R.encode_twoparam(kr.BT_SELECT, n)
    assert bt["BT_CLEAR"] == (0, 0) and kr.BT_CLEAR_CMD == 0
    assert bt["BT_NEXT"] == (0, kr.BT_NEXT_CMD) and bt["BT_PREV"] == (0, kr.BT_PREV_CMD)
    assert CORE["output_params"]["USB_DEVICE"] == R.OUTPUT_SELECTOR_REV["USB_DEVICE"]
    assert CORE["output_params"]["BT_OUT"] == R.OUTPUT_SELECTOR_REV["BT_OUT"]
    for p in CORE["mouse_params"]["buttons"]:
        mask, cmd = p["memory_pair_(mask,cmd)"]
        assert cmd == R.MOUSE_CATEGORY and R.MOUSE_MASK[p["name"]] == mask, p["name"]
    print("  Bluetooth, output and mouse-button pairs agree")


def test_modifier_aliases_cover_nayacore_alias_table():
    table = CORE["modifier_details"]["modifier_alias_table"]["names_in_order"]
    missing = [t for t in table if R.MOD_TOKEN_ALIASES.get(t, t) not in R.MOD_BIT]
    assert not missing, f"NayaCore accepts these modifier spellings and we do not: {missing}"
    print(f"  all {len(table)} vendor modifier aliases accepted")


if __name__ == "__main__":
    for fn in (test_every_shared_key_name_encodes_to_nayacore_bytes,
               test_every_nayaflow_palette_key_is_in_nayacore_table,
               test_led_colours_are_nayacore_values, test_led_subcommands_and_effects_match,
               test_bluetooth_outputs_and_mouse_pairs_match,
               test_modifier_aliases_cover_nayacore_alias_table):
        print(fn.__name__)
        fn()
    print("\nOK")
