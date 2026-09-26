"""Planning the module layout to flash: slots, list entries, and per-layer bays.

The scenario this exists for is the one the device owner described: set four module profiles on
layer 0, then change ONE of them on layer 1. Layer 0's four keep working on every layer through
inheritance, and the board ends up carrying five profiles -- the four plus layer 1's alternate.

Every rule here comes from a NayaFlow capture on 2026-09-03, not from guesswork:

    WRITE_LAYER_DATA         014c0500              layer 1, bay 0x4c -> slot 5
    WRITE_MODULE_CONFIG_LIST 00 05 05 01 10 <uuid> add entry: slot 5, type 1 (Track)
    WRITE_MODULE_CONFIG_DATA 05 ...                the config itself

No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import module_layout as ml  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

TOUCH = "9e69c41f-8da6-4441-b5c1-cb9a75319a28"
TRACK_L = "a7d0eb1c-a75a-4c88-9dc1-2d00aff33d38"
TRACK_R = "a0be68dd-f467-4946-b52f-3e3dae18d4e0"
TUNE = "64511719-37ce-4a59-8f3a-49cac408ad08"
TRACK_ALT = "28c8d0d7-e2d1-409a-a987-81e314c3c694"   # the layer-1 alternate

TYPES = {TOUCH: "TOUCH", TRACK_L: "TRACK", TRACK_R: "TRACK", TUNE: "TUNE",
         TRACK_ALT: "TRACK"}

# What the board already carries: the four stock profiles in slots 1-4.
DEVICE_LIST = [{"slot": 1, "list_id": 1, "flag": 1, "uuid": TRACK_R},
               {"slot": 2, "list_id": 2, "flag": 0, "uuid": TUNE},
               {"slot": 3, "list_id": 3, "flag": 0, "uuid": TOUCH},
               {"slot": 4, "list_id": 4, "flag": 1, "uuid": TRACK_L}]

# Slot contents. Track Right carries 21 trailing junk fields; Track Left is the clean 15.
DEVICE_SLOTS = {
    1: {i: (R.KEY_PRESS, b"\x04") for i in range(36)},
    2: {i: (R.KEY_PRESS, b"\x04") for i in range(36)},
    3: {i: (R.KEY_PRESS, b"\x04") for i in range(31)},
    4: {i: (R.KEY_PRESS, b"\x04") for i in range(15)},
}

BASE_BAYS = {"touch:keyboard_left": TOUCH, "touch:keyboard_right": TOUCH,
             "track:keyboard_left": TRACK_L, "track:keyboard_right": TRACK_R,
             "tune:keyboard_left": TUNE, "tune:keyboard_right": TUNE}


def test_layer_zero_alone_flashes_the_profiles_already_on_the_board():
    """Nothing new to allocate: every bay names a profile the board already carries."""
    out = ml.plan({0: BASE_BAYS, 1: {}, 2: {}}, TYPES, DEVICE_LIST, DEVICE_SLOTS)

    assert out["allocated"] == [], "no profile should be added"
    assert out["slot_for"] == {TOUCH: 3, TRACK_L: 4, TRACK_R: 1, TUNE: 2}, out["slot_for"]
    # Layers with no bays of their own write nothing, so the board keeps inheriting.
    assert out["bays"][1] == {} and out["bays"][2] == {}
    print("  4 profiles, slots 3/4/1/2 kept, nothing allocated")


def test_one_layer_override_adds_a_fifth_profile_in_a_new_slot():
    """The whole feature, in one assertion set: four on layer 0 plus one alternate on layer 1."""
    layer1 = dict(BASE_BAYS, **{"track:keyboard_left": TRACK_ALT})
    out = ml.plan({0: BASE_BAYS, 1: layer1, 2: BASE_BAYS}, TYPES, DEVICE_LIST, DEVICE_SLOTS)

    assert out["allocated"] == [TRACK_ALT], out["allocated"]
    assert out["slot_for"][TRACK_ALT] == 5, "must take the next free slot, not reuse 1-4"
    for cid, slot in ((TRACK_R, 1), (TUNE, 2), (TOUCH, 3), (TRACK_L, 4)):
        assert out["slot_for"][cid] == slot, "existing profiles must keep their slots"
    assert len(out["list_entries"]) == 5
    print("  5 profiles on the board; the alternate took slot 5")


def test_the_overriding_layer_names_its_slot_and_the_others_inherit():
    layer1 = dict(BASE_BAYS, **{"track:keyboard_left": TRACK_ALT})
    out = ml.plan({0: BASE_BAYS, 1: layer1, 2: BASE_BAYS}, TYPES, DEVICE_LIST, DEVICE_SLOTS)
    TRACK_LEFT_BAY = 0x4C

    assert out["bays"][0][TRACK_LEFT_BAY] == 4, "base layer names its slot outright"
    assert out["bays"][1][TRACK_LEFT_BAY] == 5, "the override names the alternate's slot"
    assert out["bays"][2][TRACK_LEFT_BAY] == ml.BAY_INHERIT, "unchanged layers inherit"
    # Bays layer 1 did NOT override still inherit, even though it listed them.
    assert out["bays"][1][0x4E] == ml.BAY_INHERIT, "tune was not overridden on layer 1"
    print("  layer 0 -> 4, layer 1 -> 5, layer 2 -> 0x78 inherit")


def test_a_disabled_bay_writes_zero_not_inherit():
    """0 disables the bay; 0x78 would silently fall back to the base layer instead."""
    out = ml.plan({0: dict(BASE_BAYS, **{"tune:keyboard_left": "disabled"})},
                  TYPES, DEVICE_LIST, DEVICE_SLOTS)
    assert out["bays"][0][0x4E] == 0
    print("  disabled bay -> 0")


def test_a_new_profile_is_templated_from_the_cleanest_slot_of_its_type():
    """We model 4 of a Track's 15 fields, so a config authored from the DB alone would drop the
    motion axes. The template must also be the 15-field slot, not the 36-field one."""
    layer1 = dict(BASE_BAYS, **{"track:keyboard_left": TRACK_ALT})
    out = ml.plan({0: BASE_BAYS, 1: layer1}, TYPES, DEVICE_LIST, DEVICE_SLOTS)

    tmpl = out["templates"][TRACK_ALT]
    assert len(tmpl) == 15, f"expected the clean Track Left slot, got {len(tmpl)} fields"
    print("  templated from the 15-field slot, not the 36-field one")


def test_the_overlay_changes_only_the_gestures_and_keeps_the_rest():
    """The overlay owns every gesture and axis the profile models -- a gesture with no row is
    unbound, as the read calls it (tests/test_module_flash_read_parity.py) -- and nothing else:
    every field it does not model passes through from the template."""
    from openflow_backend.device import module_fields as MF
    layer1 = dict(BASE_BAYS, **{"track:keyboard_left": TRACK_ALT})
    out = ml.plan({0: BASE_BAYS, 1: layer1}, TYPES, DEVICE_LIST, DEVICE_SLOTS)
    tmpl = out["templates"][TRACK_ALT]

    cfg = ml.overlay(tmpl, "TRACK", {"tap:track:button_1": "M2"})
    assert len(cfg) == len(tmpl), "overlay must not add or drop fields"
    assert cfg[0x0B] == (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, R.MOUSE_MASK["M2"]))
    gestures = MF.writable_fields("TRACK")
    axes = {h[s] for h in MF.axis_halves("TRACK").values() for s in "-+"}
    for g, i in gestures.items():
        if g != "tap:track:button_1":
            assert cfg[i] == (R.NONE_BEH, b""), f"{g} has no row, so it is written unbound"
    untouched = [i for i in tmpl if i not in set(gestures.values()) | axes]
    assert all(cfg[i] == tmpl[i] for i in untouched), "every field the profile does not model passes through"
    print(f"  gestures and axes follow the profile, {len(untouched)} other fields passed through")


def test_a_gesture_field_takes_a_keypress_as_readily_as_a_mouse_button():
    """Gesture fields are not type-locked -- a Track profile was captured with its four buttons
    bound to letters, stored as keypress records where stock holds mouse masks."""
    cfg = ml.overlay({0x0B: (R.KEY_PRESS, b"\x00")}, "TRACK", {"tap:track:button_1": "A"})
    assert cfg[0x0B][0] == R.KEY_PRESS
    print("  a letter binding encodes as a keypress record")


def test_adding_a_type_the_board_has_never_carried_is_refused_not_guessed():
    """Without a config of that type to copy, a written config would be missing fields we do
    not model. Refusing is the only safe answer."""
    float_id = "11111111-2222-3333-4444-555555555555"
    types = dict(TYPES, **{float_id: "FLOAT"})
    with pytest.raises(ml.LayoutError, match="FLOAT"):
        ml.plan({0: {"float:keyboard_left": float_id}}, types, DEVICE_LIST, DEVICE_SLOTS)
    print("  refused with a message naming the module type")


def test_slots_are_resolved_by_uuid_so_a_reshuffled_board_still_matches():
    """Slot indices move between flashes -- Tune was observed going from slot 4 to slot 2."""
    shuffled = [dict(e, slot=(6 - e["slot"])) for e in DEVICE_LIST]
    out = ml.plan({0: BASE_BAYS}, TYPES, shuffled, DEVICE_SLOTS)
    assert out["slot_for"][TRACK_R] == 5 and out["slot_for"][TRACK_L] == 2
    assert out["allocated"] == [], "matching by uuid means nothing looks new"
    print("  slots followed their uuids, nothing re-allocated")
