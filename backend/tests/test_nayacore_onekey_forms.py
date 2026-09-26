"""A key's four behaviours are written the way NayaCore 6.11.0 writes them, and read back the way it
reads them.

Read from NayaCore's own code on 2026-09-26 (NayaFlow 1.25.1; the mac build keeps its symbols):
naya_remap::Key::serializeBindingData, serializeBindingPairData, wrapDblTapRecord and readBytes.

  * slots are tap 0, hold 1 (primary bank) and double_tap 2, tap_hold 3 (second bank, +0x52)
  * both slots of a bank set  -> the 0x03 pair, each half a whole binding (type + 8 bytes)
  * one slot set              -> that action as a record of its own
  * a key with a double-tap or tap+hold has BOTH records inside the 0x10 wrapper,
    [term u16][inner type][inner param]
  * a primary with nothing in it is NONE; an empty second bank is no record at all

One deliberate difference: with only the hold-side slot set, NayaCore writes that action on its
own, which fires on a TAP (its tap+hold-only key even reads back as a double-tap). OpenFlow writes
the pair with the empty half Disabled, which is what NayaCore writes for a user's Disabled half.

What made this worth doing: every multi-behaviour key OpenFlow wrote was 24 bytes a bank, and a
board flashed from NayaFlow showed RAW_ codes for keys NayaCore had written in its short forms
(a tester's LALT + F4 read as RAW_9600013d000704). No hardware.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F          # noqa: E402
from openflow_backend.device import keymap_read as kr   # noqa: E402
from openflow_backend.device import remap as R          # noqa: E402

TERM, FLAV = 200, 1
KEYS = {"tap": "A", "hold": "B", "double_tap": "C", "tap_hold": "D"}
KP = {"A": "04000700", "B": "05000700", "C": "06000700", "D": "07000700"}
T = "c800"                                       # term 200, little-endian
PAIR = "01" + T                                  # flavour 1, term


def _rows(behaviours, keys=KEYS):
    return [{"beh": "press" if b == "tap" else b, "at": "key", "ac": keys[b]} for b in behaviours]


def _encode(rows, term=TERM, flavour=FLAV, layer_order=None):
    lo = layer_order or {}
    p = F._binding_rows_to_record(rows, term, flavour, lo)
    s = F._second_bank_record(rows, term, flavour, lo)
    return (None if p is None else (p[0], p[1].hex())), (None if s is None else (s[0], s[1].hex()))


# Every combination, primary and second bank, as bytes. Pairs are [hold type][tap type][flavour]
# [term] hold(8) tap(8); "0000000000000000" is an empty half's param, "07" its Disabled type.
Z8 = "0000000000000000"
EXPECTED = {
    ("tap",):                     ((0x01, KP["A"]), None),
    ("tap", "hold"):              ((0x03, "0101" + PAIR + KP["B"] + "00000000" + KP["A"] + "00000000"), None),
    ("tap", "double_tap"):        ((0x10, T + "01" + KP["A"]), (0x10, T + "01" + KP["C"])),
    ("tap", "tap_hold"):          ((0x10, T + "01" + KP["A"]),
                                   (0x10, T + "03" + "0107" + PAIR + KP["D"] + "00000000" + Z8)),
    ("tap", "hold", "double_tap"): ((0x10, T + "03" + "0101" + PAIR + KP["B"] + "00000000" + KP["A"] + "00000000"),
                                    (0x10, T + "01" + KP["C"])),
    ("tap", "hold", "double_tap", "tap_hold"):
        ((0x10, T + "03" + "0101" + PAIR + KP["B"] + "00000000" + KP["A"] + "00000000"),
         (0x10, T + "03" + "0101" + PAIR + KP["D"] + "00000000" + KP["C"] + "00000000")),
    ("double_tap",):              ((0x10, T + "07"), (0x10, T + "01" + KP["C"])),
    ("tap_hold",):                ((0x10, T + "07"),
                                   (0x10, T + "03" + "0107" + PAIR + KP["D"] + "00000000" + Z8)),
    ("hold",):                    ((0x03, "0107" + PAIR + KP["B"] + "00000000" + Z8), None),
    ("hold", "double_tap"):       ((0x10, T + "03" + "0107" + PAIR + KP["B"] + "00000000" + Z8),
                                   (0x10, T + "01" + KP["C"])),
}


@pytest.mark.parametrize("behaviours", list(EXPECTED), ids=lambda b: "+".join(b))
def test_each_combination_is_written_in_nayacore_s_form(behaviours):
    assert _encode(_rows(behaviours)) == EXPECTED[behaviours]


def test_the_short_forms_are_short():
    """What adopting NayaCore's forms buys: a tap + double-tap key is 7 + 7 bytes, not 24 + 24,
    and a double-tap-only key's primary is the 3-byte wrapped Disabled."""
    (_, p), (_, s) = _encode(_rows(("tap", "double_tap")))
    assert len(bytes.fromhex(p)) == 7 and len(bytes.fromhex(s)) == 7
    (_, p), _s = _encode(_rows(("double_tap",)))
    assert len(bytes.fromhex(p)) == 3


# --- NayaFlow's own flashes ------------------------------------------------------------------ #

def test_reproduces_nayaflow_s_2026_09_17_flash_of_key_55():
    """device/out/onekey-timing-20260917-analysis.txt: tap N / hold B / double-tap B / tap+hold N
    at term 180, flavour 0, both banks as NayaFlow wrote them."""
    rows = _rows(("tap", "hold", "double_tap", "tap_hold"),
                 {"tap": "N", "hold": "B", "double_tap": "B", "tap_hold": "N"})
    assert _encode(rows, term=180, flavour=0) == (
        (0x10, "b40003010100b400" + "0500070000000000" + "1100070000000000"),
        (0x10, "b40003010100b400" + "1100070000000000" + "0500070000000000"))


def test_reads_the_tester_s_board_instead_of_showing_raw():
    """The two keys a tester's flash preview listed as 'cannot be written': NayaCore's 7-byte
    wrapper around a plain key, term 150."""
    assert kr.translate(0x10, bytes.fromhex("9600013d000704"), {}) == [("press", "shortcut_alias", "LALT + F4")]
    assert kr.translate(0x10, bytes.fromhex("960001e2000700"), {}) == [("press", "modifier", "LALT")]


# --- reading back ---------------------------------------------------------------------------- #

def _read_back(behaviours, keys=KEYS, layer_order=None):
    """Encode, then decode both records the way decode_keymap does (second bank renamed)."""
    lo = layer_order or {}
    rows = [{"beh": "press" if b == "tap" else b, "at": at, "ac": code}
            for b, (at, code) in keys.items() if b in behaviours]
    out = []
    p = F._binding_rows_to_record(rows, TERM, FLAV, lo)
    s = F._second_bank_record(rows, TERM, FLAV, lo)
    order_to_layer = {v: k for k, v in lo.items()}
    out += kr.translate(p[0], p[1], order_to_layer) if p else []
    if s:
        out += [(kr.SECOND_BANK_BEHAVIOR.get(b, b), at, c) for b, at, c in kr.translate(s[0], s[1], order_to_layer)]
    return out


@pytest.mark.parametrize("n", range(1, 5))
def test_every_combination_reads_back_as_what_was_set(n):
    """Each behaviour lands in its own slot whichever others are empty -- a Disabled half is named
    as such, never moved into the slot beside it."""
    keys = {b: ("key", k) for b, k in KEYS.items()}
    for combo in itertools.combinations(("tap", "hold", "double_tap", "tap_hold"), n):
        got = {(b, c) for b, _at, c in _read_back(combo, keys)}
        want = {("press" if b == "tap" else b, KEYS[b]) for b in combo}
        assert want <= got, (combo, got)
        extra = {x for x in got - want if x[1] != "DISABLE"}
        assert not extra, (combo, extra)


def test_a_disabled_half_round_trips_byte_for_byte():
    """Read -> rows -> write gives the board's own bytes back, for the forms NayaCore writes when
    a user picks Disabled for one half and for OpenFlow's own hold-only and tap+hold-only keys."""
    for typ, hexparam in ((0x03, "0107" + PAIR + KP["B"] + "00000000" + Z8),        # tap Disabled, hold B
                          (0x03, "0701" + PAIR + Z8 + KP["A"] + "00000000")):       # tap A, hold Disabled
        rows = [{"beh": b, "at": at, "ac": c} for b, at, c in kr.translate(typ, bytes.fromhex(hexparam), {})]
        assert F._binding_rows_to_record(rows, TERM, FLAV, {}) == (typ, bytes.fromhex(hexparam)), rows


def test_a_disabled_double_tap_is_a_behaviour_not_an_absence():
    """NayaCore's Disabled double-tap with no tap+hold: a wrapped NONE in the second bank. The
    key waits for a second tap and then does nothing, which is not what a key with no double-tap
    does, so it reads back as a Disabled double-tap and is written back the same way."""
    assert kr.translate(0x10, bytes.fromhex(T + "07"), {}) == [("press", "none", "DISABLE")]
    rows = [{"beh": "press", "at": "key", "ac": "A"},
            {"beh": "double_tap", "at": "none", "ac": "DISABLE"}]
    assert _encode(rows) == ((0x10, T + "01" + KP["A"]), (0x10, T + "07"))


def test_any_action_can_sit_in_any_slot():
    """A half is a whole binding, so a layer switch or a Bluetooth device works as a double-tap
    or a tap+hold, including one that needs both params."""
    lo = {"L2": 2}
    keys = {"tap": ("key", "A"), "hold": ("layer_polite_hold", "MO_LAYER_L2"),
            "double_tap": ("layer_rude_toggle", "TO_LAYER_L2"), "tap_hold": ("bluetooth", "BT_DEVICE_2")}
    got = _read_back(tuple(keys), keys, lo)
    assert ("double_tap", "layer_rude_toggle", "TO_LAYER_L2") in got
    assert ("tap_hold", "bluetooth", "BT_DEVICE_2") in got
    assert ("hold", "layer_polite_hold", "MO_LAYER_L2") in got
    s = F._second_bank_record([{"beh": b, "at": at, "ac": c} for b, (at, c) in keys.items()], TERM, FLAV, lo)
    assert s[1].hex() == T + "03" + "000c" + PAIR + "0300000002000000" + "0200000000000000"


def test_a_double_tap_with_no_encoder_raises_so_the_board_keeps_it():
    """Returning None here let _own_second_bank blank the slot (see test_second_bank_gc)."""
    with pytest.raises(R.RemapEncodeError):
        F._second_bank_record([{"beh": "press", "at": "key", "ac": "A"},
                               {"beh": "double_tap", "at": "macro", "ac": "M1"}], TERM, FLAV, {})


def test_an_unset_half_written_by_openflow_up_to_0_4_0_still_reads_as_unset():
    """Old boards carry a keypress of zeros in an unset half (SCRUM-96). It stays unset."""
    old = bytes.fromhex(T + "03" + "0101" + PAIR + "00000000" * 2 + KP["A"] + "00000000")
    assert kr.translate(0x10, old, {}) == [("press", "key", "A")]
