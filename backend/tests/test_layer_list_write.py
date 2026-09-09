"""The device's layer IDENTITY table, which OpenFlow never wrote.

THE BUG. `WRITE_LAYER_LIST` (0x30/0x1002) existed in remap.py and was referenced exactly once in
flash.py -- inside a docstring. `DesiredState.layer_uuids` was declared and never populated or
read. So every OpenFlow flash rewrote layer records and LED maps while leaving the board still
advertising whatever layer UUIDs were last written to it, which in practice were NayaFlow's.

That is not cosmetic. The layer list is what a READ matches app layers against
(db/keymap_import.py reads `layer_uuids`). On the reference board it said:

    index 0 -> Naya Default Windows / Typing
    index 1 -> Naya Default Windows / Keypad + Arrow Keys
    index 2 -> Naya Default Windows / System

while the records on those indexes came from an entirely different profile. Importing from that
board therefore attributed the user's bindings to the wrong profile's layers, and re-flashing
propagated the confusion. It presented as "layer switching broke after I reordered my layers".

Both payload forms are copied from captured NayaCore flashes and asserted byte-for-byte here,
because they are the parts that cannot be re-derived from a device read:
  add/replace  docs/write-protocol-spec.md:137   device/out/flash2-analysis.txt:287
  delete       docs/write-protocol-spec.md:189   device/out/flash3-analysis.txt:141

The tests themselves need no hardware, but the replace-an-existing-index case below WAS
confirmed on a real board (2026-09-08) -- see that test. No capture covered it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F     # noqa: E402
from openflow_backend.device import remap as R     # noqa: E402

U1 = "878610a4-c743-4723-a599-32655479dee2"
U2 = "05a59817-d3a4-42df-9b95-9d5f85067603"


def state(uuids: dict[int, str], leds: dict | None = None) -> F.DesiredState:
    d = F.DesiredState()
    for idx, u in uuids.items():
        d.layers[idx] = {}
        d.layer_uuids[idx] = R.layer_uuid_bytes(u)
    if leds:
        d.leds.update(leds)
    return d


# --- the captured bytes ------------------------------------------------------------------------ #

def test_the_add_payload_matches_the_captured_nayacore_frame():
    """flash2: two layers added. `00` + `[idx][id][00][10][uuid16]` each, NEW entries only."""
    got = R.encode_layer_list_entries([(3, R.layer_uuid_bytes(U1), 0), (4, R.layer_uuid_bytes(U2), 0)])
    assert got.hex() == (
        "00"
        "03030010" "878610a4c7434723a59932655479dee2"
        "04040010" "05a59817d3a442df9b959d5f85067603"
    ), got.hex()


def test_the_delete_payload_matches_the_captured_nayacore_frame():
    """flash3: the same two removed. `[idx] 00 00 00`, and the set sent TWICE in one frame."""
    got = R.encode_layer_list_deletes([3, 4])
    assert got.hex() == "00" "03000000" "04000000" "03000000" "04000000", got.hex()


def test_the_uuid_bytes_are_the_devices_own_byte_order():
    """Mirrors keymap_read's `blk[4:20].hex()` re-dashed, rather than trusting uuid.UUID."""
    assert R.layer_uuid_bytes(U1).hex() == U1.replace("-", "")
    assert len(R.layer_uuid_bytes(U1)) == 16


def test_a_bad_uuid_is_refused_rather_than_padded():
    for bad in ("", "not-a-uuid", "878610a4", "8" * 34):
        with pytest.raises(ValueError):
            R.layer_uuid_bytes(bad)


def test_an_entry_with_a_wrong_length_id_is_refused():
    with pytest.raises(ValueError, match="16 bytes"):
        R.encode_layer_list_entries([(0, b"\x01\x02", 0)])


def test_an_unknown_animation_is_refused_rather_than_written_raw():
    """Byte 2 is the layer's LED animation and only 0-3 are known. Writing an unrecognised value
    would leave the board in a state no application can describe."""
    with pytest.raises(ValueError, match="animation"):
        R.encode_layer_list_entries([(0, R.layer_uuid_bytes(U1), 9)])


def test_the_animation_byte_is_carried_not_zeroed():
    """THE BUG: byte 2 was hardcoded 0x00, so any flash that wrote the layer list silently reset
    every layer to solid. Read off the probe board as breathe=1 / swirl=3 / spectrum=2 (ZMK's
    order; the two were transcribed the other way round until 2026-09-09)."""
    got = R.encode_layer_list_entries([(0, R.layer_uuid_bytes(U1), 1),
                                       (1, R.layer_uuid_bytes(U2), 3)])
    assert got[1:4].hex() == "000001", got[1:4].hex()      # idx 0, id 0, animation 1 (breathe)
    assert got[21:24].hex() == "010103", got[21:24].hex()  # idx 1, id 1, animation 3 (swirl)


def test_changing_only_the_animation_still_rewrites_the_entry():
    """The animation lives in the same 20 bytes as the uuid, so a layer whose identity has not
    moved but whose effect has must still be written."""
    d = state({0: U1})
    d.layer_animations[0] = 2                      # swirl
    cur = state({0: U1})
    cur.layer_animations[0] = 0                    # board still says solid
    ops = F._layer_list_ops(d, cur)
    assert len(ops) == 1, "an animation change was not written"
    assert ops[0].payload[3] == 2


def test_an_unchanged_animation_writes_nothing():
    d, cur = state({0: U1}), state({0: U1})
    d.layer_animations[0] = cur.layer_animations[0] = 2
    assert F._layer_list_ops(d, cur) == []


# --- when it fires ------------------------------------------------------------------------------ #

def test_nothing_is_written_when_the_board_already_agrees():
    """The property that keeps an ordinary flash ordinary. Rewriting identities on every flash
    would be a change we have no capture for, on every single flash."""
    d = state({0: U1, 1: U2})
    assert F._layer_list_ops(d, state({0: U1, 1: U2})) == []


def test_the_stale_identity_case_is_what_gets_rewritten():
    """The reference board's actual fault: right number of layers, wrong UUIDs on them.

    VERIFIED ON HARDWARE 2026-09-08. Writing an index that already holds a different UUID
    REPLACES it rather than appending -- the one thing no capture covered, since NayaCore was
    only ever seen adding brand-new indexes. Before: the board reported Naya Default Windows'
    three layer UUIDs. After: Travis' Create's three, and a read-back import matched that
    profile with 3 layers, not 6."""
    d = state({0: U1, 1: U2})
    ops = F._layer_list_ops(d, state({0: U2, 1: U1}))
    assert len(ops) == 1 and ops[0].sub == R.WRITE_LAYER_LIST
    assert ops[0].payload == R.encode_layer_list_entries(
        [(0, R.layer_uuid_bytes(U1), 0), (1, R.layer_uuid_bytes(U2), 0)])


def test_only_the_changed_entries_are_sent():
    """NayaCore sent new entries only, not the whole list."""
    ops = F._layer_list_ops(state({0: U1, 1: U2}), state({0: U1}))
    assert len(ops) == 1
    assert ops[0].payload == R.encode_layer_list_entries([(1, R.layer_uuid_bytes(U2), 0)])
    assert "new" in ops[0].label


def test_a_board_we_have_not_read_gets_the_whole_table():
    ops = F._layer_list_ops(state({0: U1, 1: U2}), None)
    assert len(ops) == 1
    assert ops[0].payload == R.encode_layer_list_entries(
        [(0, R.layer_uuid_bytes(U1), 0), (1, R.layer_uuid_bytes(U2), 0)])


def test_a_removed_layer_is_deleted_and_then_wiped():
    """The firmware does not clear a deleted layer's data or LED map; NayaCore sends both."""
    d = state({0: U1})
    cur = state({0: U1, 1: U2}, leds={1: {i: (0, 0) for i in range(136)}})
    ops = F._layer_list_ops(d, cur)
    kinds = [(o.sub, o.label) for o in ops]
    assert ops[0].sub == R.WRITE_LAYER_LIST and "remove 1" in ops[0].label
    assert any(s == R.WRITE_LAYER_DATA and "wipe layer 1" in l for s, l in kinds), kinds
    assert any(s == R.WRITE_LED_MAP_DATA and "wipe led 1" in l for s, l in kinds), kinds


def test_the_led_wipe_covers_every_led_the_board_reports():
    """LED_COUNT is 88 while a real read returns 136 per layer. Wiping 88 would leave a third of
    a deleted layer lit -- so the wipe is sized from the device read, not the constant."""
    cur = state({0: U1, 1: U2}, leds={1: {i: (0, 0) for i in range(136)}})
    ops = F._layer_list_ops(state({0: U1}), cur)
    wipe = next(o for o in ops if o.label == "wipe led 1")
    assert len(wipe.payload) == 1 + 136 * 4, len(wipe.payload)


def test_a_wiped_layer_blanks_keys_as_none_and_bays_as_zero():
    payload = F._blank_layer_payload(3)
    assert payload[0] == 3
    body = payload[1:]
    assert bytes.fromhex("000700") in body            # position 0 -> none
    # A module bay is `00 00`, not `07 00` -- 0 means "no module", which is NayaFlow's own idiom.
    bay = min(F.MODULE_SLOT_POSITIONS)
    assert bytes([bay, 0x00, 0x00]) in body, body.hex()


# --- the guards --------------------------------------------------------------------------------- #

def test_a_partial_identity_table_is_never_written():
    """Worse than writing nothing: it would name some indexes and leave others stale, which is
    the exact fault this change exists to fix. Fixtures with non-uuid layer ids land here."""
    d = F.DesiredState()
    d.layers = {0: {}, 1: {}}
    d.layer_uuids = {0: R.layer_uuid_bytes(U1)}       # layer 1 has no id
    assert F._layer_list_ops(d, None) == []


def test_no_identity_information_means_no_write():
    d = F.DesiredState()
    d.layers = {0: {}}
    assert F._layer_list_ops(d, None) == []


def test_the_list_write_comes_before_any_layer_data():
    """Ordering is from the captures: the device is told what the layers ARE before it is told
    what is on them."""
    d = state({0: U1})
    d.layers[0] = {5: (0x01, bytes.fromhex("04000700"))}
    ops = F.compute_plan(d, state({0: U2}))
    subs = [o.sub for o in ops]
    assert subs.index(R.WRITE_LAYER_LIST) < subs.index(R.WRITE_LAYER_DATA), subs
