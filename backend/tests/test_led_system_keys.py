"""Record type 0x09 is the LED system keys, and we showed all fourteen of them as "LED".

THE GAP. `translate` returned `Unmapped("led:<hex>")` for every 0x09 record, so a board carrying
LED_SOLID, LED_BREATHE, LED_SWIRL, LED_SPEC, the brightness and speed pairs and the four colour
keys read back as fourteen identical unknowns on the virtual keyboard. There was no encoder
either, so reading a profile off the board and flashing it back dropped all fourteen and the keys
silently kept whatever they already had.

WHERE THE NAMES COME FROM. Not guessed, and not taken from ZMK's enum -- Naya's subcommand
numbering does not match ZMK's. NayaFlow flashed its own default profile to the reference board on
2026-09-08, and each record was paired with the action code NayaFlow's own database holds for that
exact layer and position. Every pair below is that correlation:

    pos  9  0d 00000000  LED_SOLID           pos 39  00 00000000  LED_EFFECT_ON_OFF
    pos 10  0d 01000000  LED_BREATHE         pos 24  07 00000000  LED_BRIGHTNESS_UP
    pos 11  0d 02000000  LED_SWIRL           pos 40  08 00000000  LED_BRIGHTNESS_DOWN
    pos 12  0d 03000000  LED_SPEC            pos 25  09 00000000  LED_SPEED_UP
    pos 23  0b 00000000  LED_EFFECT          pos 41  0a 00000000  LED_SPEED_DOWN
    pos 55  0f 64000000  LED_COLOR_WHITE     pos 57  0f 64647800  LED_COLOR_GREEN
    pos 56  0f 64640000  LED_COLOR_RED       pos 58  0f 6464f000  LED_COLOR_BLUE

The colour argument is [brightness u8][saturation u8][hue u16 LE] -- so the LIVE path carries
brightness AND saturation, where the stored per-key map holds hue + saturation only. White is
saturation 0 in both, which is the cross-check that the two agree.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F          # noqa: E402
from openflow_backend.device import keymap_read as kr   # noqa: E402
from openflow_backend.device import remap as R          # noqa: E402

# The bytes the board actually returned, against NayaFlow's own names for them.
CAPTURED = [
    ("0d00000000000000", "LED_SOLID"),
    ("0d00000001000000", "LED_BREATHE"),
    ("0d00000002000000", "LED_SWIRL"),
    ("0d00000003000000", "LED_SPEC"),
    ("0b00000000000000", "LED_EFFECT"),
    ("0700000000000000", "LED_BRIGHTNESS_UP"),
    ("0800000000000000", "LED_BRIGHTNESS_DOWN"),
    ("0900000000000000", "LED_SPEED_UP"),
    ("0a00000000000000", "LED_SPEED_DOWN"),
    ("0000000000000000", "LED_EFFECT_ON_OFF"),
    ("0f00000064000000", "LED_COLOR_WHITE"),
    ("0f00000064640000", "LED_COLOR_RED"),
    ("0f00000064647800", "LED_COLOR_GREEN"),
    ("0f0000006464f000", "LED_COLOR_BLUE"),
]


@pytest.mark.parametrize("hexp,code", CAPTURED)
def test_every_captured_record_decodes_to_nayaflows_own_name(hexp, code):
    assert kr.decode_rgb_system(bytes.fromhex(hexp)) == code


@pytest.mark.parametrize("hexp,code", CAPTURED)
def test_every_name_encodes_back_to_the_captured_bytes(hexp, code):
    assert R.encode_rgb_system(code).hex() == hexp


@pytest.mark.parametrize("hexp,code", CAPTURED)
def test_translate_surfaces_the_name_not_a_raw_blob(hexp, code):
    """The user-visible half: the virtual keyboard showed a bare 'LED' for all of these."""
    got = kr.translate(kr.RGB_SYS, bytes.fromhex(hexp), {})
    assert got == [("press", "LED", code)], got
    assert not isinstance(got[0][2], kr.Unmapped)


@pytest.mark.parametrize("hexp,code", CAPTURED)
def test_the_flash_encoder_no_longer_drops_them(hexp, code):
    """Without an encoder these were dropped and the key kept its old binding."""
    rec = F._binding_rows_to_record([{"beh": "press", "at": "LED", "ac": code}], 200, 0, {})
    assert rec == (kr.RGB_SYS, bytes.fromhex(hexp)), rec


def test_white_is_saturation_zero_here_too():
    """Cross-check between the live colour path and the stored map: both call white saturation 0.
    If these ever disagree, one of the two decodes is wrong."""
    arg = int.from_bytes(R.encode_rgb_system("LED_COLOR_WHITE")[4:8], "little")
    brightness, saturation, hue = arg & 0xFF, (arg >> 8) & 0xFF, (arg >> 16) & 0xFFFF
    assert (brightness, saturation, hue) == (100, 0, 0)
    assert kr.hex_to_hue_sat("#ffffff") == (0, 0)


def test_the_colour_argument_packs_hue_where_we_think_it_does():
    """Green is hue 120 and blue 240 -- ordinary hue degrees, not a palette index."""
    for code, hue in [("LED_COLOR_RED", 0), ("LED_COLOR_GREEN", 120), ("LED_COLOR_BLUE", 240)]:
        arg = int.from_bytes(R.encode_rgb_system(code)[4:8], "little")
        assert (arg >> 16) & 0xFFFF == hue, code


def test_an_unknown_subcommand_is_reported_rather_than_guessed():
    """Naya's numbering is not ZMK's, so an unrecognised value must not be rounded to whichever
    LED key looks closest -- it stays raw and gets flagged."""
    assert kr.decode_rgb_system(bytes.fromhex("ff00000000000000")) is None
    got = kr.translate(kr.RGB_SYS, bytes.fromhex("ff00000000000000"), {})
    assert isinstance(got[0][2], kr.Unmapped)


def test_an_unknown_colour_is_not_forced_onto_a_named_one():
    assert kr.decode_rgb_system(bytes.fromhex("0f00000064643c00")) is None   # hue 60, unnamed


def test_a_short_param_decodes_to_nothing_rather_than_a_wrong_key():
    for short in ("", "0d", "0d000000"[:6]):
        assert kr.decode_rgb_system(bytes.fromhex(short)) is None


def test_encoding_an_unknown_led_action_raises_rather_than_inventing_bytes():
    with pytest.raises(R.RemapEncodeError):
        R.encode_rgb_system("LED_DISCO_INFERNO")


def test_the_tables_are_built_from_one_source():
    """The encoder derives its tables from the decoder's, so they cannot drift apart."""
    for code in list(kr.RGB_SUBCOMMAND.values()) + list(kr.RGB_EFFECTS.values()) \
            + list(kr.RGB_COLORS.values()):
        assert kr.decode_rgb_system(R.encode_rgb_system(code)) == code
