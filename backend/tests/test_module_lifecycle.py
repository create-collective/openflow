"""Creating, selecting and removing a module profile -- the whole lifecycle, from captures.

All three operations were captured from NayaFlow 1.25.1 on 2026-09-03 and are reproduced here
byte for byte, because these are the writes that add and REMOVE data.

    add     WRITE_MODULE_CONFIG_DATA  <slot> <fields>      the config
            WRITE_MODULE_CONFIG_LIST  00 <slot><id><type>10<uuid>
            WRITE_LAYER_DATA          <layer> <bay> <slot> 00

    remove  WRITE_LAYER_DATA          <layer> <bay> 00 00  (bay -> disabled)
            WRITE_MODULE_CONFIG_LIST  00 <slot> 00 00 00   (delete the entry)
            WRITE_MODULE_CONFIG_DATA  <slot> <40 empty records>  (blank the slot)

A bay holds one of three values per layer: 0x78 inherit-from-layer-0, 0 disabled, or a slot
number. Inherit resolves to the BASE layer, not the nearest layer below -- confirmed by pressing
the buttons on layer 2 while layer 1 overrode the same bay.
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

# Captured payloads, verbatim.
ADD_LIST = "000505011036df34afa5cf4efeb8aa667bd33a3d48"
ADD_BAY = "014c0500"
DEL_LIST = "0005000000"
DEL_BAYS = "014c00004f0000"
BLANK_LEN = 121                      # 1 slot byte + 40 * 3


def test_add_list_entry_matches_the_capture():
    uuid = bytes.fromhex("36df34afa5cf4efeb8aa667bd33a3d48")
    got = R.encode_module_config_list([(5, 5, 1, uuid)])
    assert got.hex() == ADD_LIST, got.hex()
    back = R.parse_module_config_list(got)[0]
    assert (back["slot"], back["flag"]) == (5, 1), "slot / module type did not round-trip"
    print("  add: list entry byte-exact, round-trips to slot 5 type 1 (Track)")


def test_delete_list_entry_matches_the_capture():
    got = R.encode_module_config_list_delete([5])
    assert got.hex() == DEL_LIST, got.hex()
    # a deletion carries no uuid, so parse must not report it as a live entry
    assert R.parse_module_config_list(got) == [], "a deletion was parsed as a live entry"
    print("  delete: 00 05 00 00 00, byte-exact, and not mistaken for an entry")


def test_blank_slot_matches_the_capture():
    b = R.encode_module_config_blank(5)
    assert len(b) == BLANK_LEN, f"expected {BLANK_LEN} bytes, got {len(b)}"
    assert b[0] == 5
    recs = list(kr.parse_records(b[1:]))
    assert len(recs) == R.MODULE_SLOT_FIELDS == 40
    assert all(t == 0 and not v for _f, t, v in recs), "blanking must use type-0 empty records"
    assert [f for f, _t, _v in recs] == list(range(40)), "fields must be 0..39 in order"
    print("  blank: 40 type-0 records -- NayaFlow's idiom, not type-7 clears")


def test_bay_values_are_the_three_states():
    """A short write is what leaves a slot holding a previous module's tail, so blanking has to
    address every field -- that is why the blank is a full 40 records rather than a clear."""
    assert len(R.encode_module_config_blank(1)) > len(R.encode_module_config(1, [])), \
        "a blank must be a full-length write, not an empty one"
    # bays live in layer data as ordinary records
    bay = R.record(0x4C, 5, b"")
    assert bay.hex() == "4c0500", "bay assignment is [position][slot][len 0]"
    assert R.record(0x4C, 0, b"").hex() == "4c0000", "disabled is slot 0"
    assert R.record(0x4C, 0x78, b"").hex() == "4c7800", "inherit is 0x78"
    print("  bay: slot N / 0 disabled / 0x78 inherit, encoded as a plain layer record")


def test_module_slot_positions_are_the_eight_bays():
    assert list(F.MODULE_SLOT_POSITIONS) == list(range(0x4A, 0x52)), "8 bays"
    # 4 module types x 2 sides, in type order
    assert len(list(F.MODULE_SLOT_POSITIONS)) == 8
    print("  8 bays at 0x4a-0x51 = Touch/Track/Tune/Float, left then right")


if __name__ == "__main__":
    for fn in (test_add_list_entry_matches_the_capture,
               test_delete_list_entry_matches_the_capture,
               test_blank_slot_matches_the_capture,
               test_bay_values_are_the_three_states,
               test_module_slot_positions_are_the_eight_bays):
        print(fn.__name__)
        fn()
    print("\nOK")
