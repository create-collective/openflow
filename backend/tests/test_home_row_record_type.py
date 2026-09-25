"""A tap+hold key is written as 0x03 unless the second bank is in play.

The record type is behaviour, not a label. 0x10 (OneKey) waits for a possible double-tap before
its tap goes out, so on a home-row mod the next key lands first: "few" typed as "efw", "different"
as "dierent". 0x03 (MOD_TAP) sends the tap in order. Measured on hardware 2026-09-25 with
tools/c11_homerow_timing.py (D/F/J/K as hold-mod/tap-letter, same flavour and term): 0x10
garbled 5 fast sentences of 5, 0x03 typed them clean.

NayaFlow draws the same line. Its captured flash (hold-tap-fixture.json) holds six tap+hold keys:
the five with no second-bank record are 0x03, and 0x35, whose shadow 0x87 is also written, is
0x10. This file builds those keys through the flash encoder and asks for NayaFlow's bytes.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

_FIXTURE = json.loads((Path(__file__).with_name("hold-tap-fixture.json")).read_text())
RECORDS = {pos: (typ, param) for pos, typ, param in
           kr.parse_records(bytes.fromhex(_FIXTURE["write_layer_data_payload"])[1:])}
FLAVOUR, TERM = 2, 194          # NayaFlow's settings the day of that capture


def rows(pos: int, tap: tuple[str, str], hold: tuple[str, str], *extra: dict) -> list[dict]:
    return [{"beh": "tap", "at": tap[0], "ac": tap[1], "p": pos},
            {"beh": "hold", "at": hold[0], "ac": hold[1], "p": pos}, *extra]


def test_home_row_mods_come_out_as_nayaflow_wrote_them():
    """The five tap+hold keys with nothing in the second bank: 0x03, byte for byte."""
    for pos, tap, hold in ((0x20, ("key", "A"), ("modifier", "LCTRL")),
                           (0x21, ("key", "S"), ("modifier", "LSHIFT")),
                           (0x25, ("key", "DELETE"), ("key", "BACKSPACE")),
                           (0x3F, ("modifier", "LGUI"), ("modifier", "LCTRL")),
                           (0x43, ("key", "RETURN"), ("modifier", "LALT"))):
        got = F._binding_rows_to_record(rows(pos, tap, hold), TERM, FLAVOUR, {})
        assert got == RECORDS[pos], f"pos {pos:#04x}: {got} != captured {RECORDS[pos]}"
        assert got[0] == R.HOLD_TAP_HOME


def test_a_key_with_a_second_bank_behaviour_stays_onekey():
    """0x35 also carries a double-tap / tap+hold (shadow 0x87), so its primary is 0x10."""
    extra = ({"beh": "double_tap", "at": "key", "ac": "BACKSPACE", "p": 0x35},
             {"beh": "tap_hold", "at": "key", "ac": "BACKSPACE", "p": 0x35})
    got = F._binding_rows_to_record(
        rows(0x35, ("key", "BACKSPACE"), ("modifier", "LCTRL"), *extra), TERM, FLAVOUR, {})
    assert got == RECORDS[0x35], f"{got} != captured {RECORDS[0x35]}"
    assert got[0] == R.HOLD_TAP_ONEKEY


def test_the_0x03_record_reads_back_as_the_same_key():
    """What the board returns decodes to the tap and hold that were written."""
    typ, param = F._binding_rows_to_record(
        rows(0x23, ("key", "F"), ("modifier", "LSHIFT")), 200, 1, {})
    assert typ == R.HOLD_TAP_HOME
    assert kr.translate(typ, param, {}) == [("press", "key", "F"), ("hold", "modifier", "LSHIFT")]


if __name__ == "__main__":
    for fn in (test_home_row_mods_come_out_as_nayaflow_wrote_them,
               test_a_key_with_a_second_bank_behaviour_stays_onekey,
               test_the_0x03_record_reads_back_as_the_same_key):
        print(fn.__name__)
        fn()
    print("\nOK")
