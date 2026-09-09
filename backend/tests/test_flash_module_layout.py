"""The write plan a per-layer module layout produces.

This is the path that changes the module set on the board, and it is the one that has bricked
this keyboard before -- so the plan is asserted op by op, not just "it produced something".

The scenario is the device owner's: four profiles chosen on the base layer, then one of them
swapped on layer 1. The board should end up carrying five, with the four it already had left
untouched.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import module_layout as ml  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

PID = "profile-1"
TOUCH = "9e69c41f-8da6-4441-b5c1-cb9a75319a28"
TRACK_L = "a7d0eb1c-a75a-4c88-9dc1-2d00aff33d38"
TRACK_R = "a0be68dd-f467-4946-b52f-3e3dae18d4e0"
TUNE = "64511719-37ce-4a59-8f3a-49cac408ad08"
TRACK_ALT = "28c8d0d7-e2d1-409a-a987-81e314c3c694"

NAMES = {TOUCH: ("Touch", "TOUCH"), TRACK_L: ("Track L", "TRACK"), TRACK_R: ("Track R", "TRACK"),
         TUNE: ("Tune", "TUNE"), TRACK_ALT: ("Track L alt", "TRACK")}

BASE = {"touch:keyboard_left": TOUCH, "touch:keyboard_right": TOUCH,
        "track:keyboard_left": TRACK_L, "track:keyboard_right": TRACK_R,
        "tune:keyboard_left": TUNE, "tune:keyboard_right": TUNE}

# The board carries the four stock profiles. Track Left is the clean 15-field config.
MOD_READ = {
    "by_uuid": {TRACK_R: 1, TUNE: 2, TOUCH: 3, TRACK_L: 4},
    "slots": {
        1: [{"field": i, "type": R.KEY_PRESS, "value": "04"} for i in range(36)],
        2: [{"field": i, "type": R.KEY_PRESS, "value": "04"} for i in range(36)],
        3: [{"field": i, "type": R.KEY_PRESS, "value": "04"} for i in range(31)],
        4: [{"field": i, "type": R.KEY_PRESS, "value": "04"} for i in range(15)],
    },
}


def _db(bays_per_layer):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE layers (id TEXT, order_id INT, profile_id TEXT);
        CREATE TABLE module_configs (id TEXT, name TEXT, type TEXT, captured_from TEXT);
        -- Real schema has this; the flash reads it to write speeds and tick feedback
        -- into the module's setting fields.
        CREATE TABLE IF NOT EXISTS module_settings (module_config_id TEXT,
                                      correlation_id TEXT, value TEXT, type TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (module_config_id TEXT, behavior TEXT, action_code TEXT,
                                      direction TEXT DEFAULT "+", invert INT DEFAULT 0);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT,
                                             module_config_id TEXT, binding_location TEXT,
                                             state TEXT);
    """)
    for cid, (name, typ) in NAMES.items():
        conn.execute("INSERT INTO module_configs VALUES (?,?,?,NULL)", (cid, name, typ))
    for i, code in zip((1, 2, 3, 4), ("M1", "M3", "M2", "M4")):
        conn.execute("INSERT INTO module_bindings (module_config_id,behavior,action_code) VALUES (?,?,?)",
                     (TRACK_ALT, f"tap:track:button_{i}", code))
    for order, bays in bays_per_layer.items():
        conn.execute("INSERT INTO layers VALUES (?,?,?)", (f"l{order}", order, PID))
        for loc, cid in bays.items():
            conn.execute("INSERT INTO module_config_bindings VALUES (?,?,?,?,?)",
                         (PID, f"l{order}", cid, loc, None))
    conn.commit()
    return conn


def _desired(bays_per_layer):
    """A DesiredState with the layout applied, as the flash endpoint builds it."""
    d = F.DesiredState()
    d.profile_id = PID
    for order in bays_per_layer:
        d.layers[order], d.leds[order] = {}, {}
    conn = _db(bays_per_layer)
    layout = F.apply_module_layout(d, conn, MOD_READ)
    conn.close()
    return d, layout


def _ops(d, current=None):
    return F.compute_plan(d, current, full=True)


def test_no_override_reuses_every_slot_and_writes_no_module_data():
    """The four profiles are already on the board, so nothing is added and no config is sent."""
    d, layout = _desired({0: BASE, 1: {}, 2: {}})

    assert layout["allocated"] == []
    assert d.modules == {}, "a profile already on the board must not be rewritten"
    assert sorted(d.module_list) == [1, 2, 3, 4]
    data = [o for o in _ops(d) if o.sub == R.WRITE_MODULE_CONFIG_DATA]
    assert data == [], f"expected no module config writes, got {[o.label for o in data]}"
    print("  4 profiles reused, 0 config writes")


def test_one_override_adds_exactly_one_slot_and_one_config_write():
    layer1 = dict(BASE, **{"track:keyboard_left": TRACK_ALT})
    d, layout = _desired({0: BASE, 1: layer1, 2: {}})

    assert layout["allocated"] == [TRACK_ALT]
    assert list(d.modules) == [5], "only the new profile gets a config write"
    assert sorted(d.module_list) == [1, 2, 3, 4, 5]

    data = [o for o in _ops(d) if o.sub == R.WRITE_MODULE_CONFIG_DATA]
    lists = [o for o in _ops(d) if o.sub == R.WRITE_MODULE_CONFIG_LIST]
    assert len(data) == 1 and "slot 5" in data[0].label, [o.label for o in data]
    assert len(lists) == 1 and "5 entries" in lists[0].label, [o.label for o in lists]
    print(f"  {data[0].label}; {lists[0].label}")


def test_the_bay_bytes_match_the_captured_write():
    """NayaFlow sent 014c0500 for layer 1, bay 0x4c -> slot 5: the slot lives in the record's
    TYPE field with an empty param."""
    layer1 = dict(BASE, **{"track:keyboard_left": TRACK_ALT})
    d, _ = _desired({0: BASE, 1: layer1, 2: BASE})
    TRACK_LEFT_BAY = 0x4C

    assert d.layers[0][TRACK_LEFT_BAY] == (4, b""), d.layers[0][TRACK_LEFT_BAY]
    assert d.layers[1][TRACK_LEFT_BAY] == (5, b"")
    assert d.layers[2][TRACK_LEFT_BAY] == (ml.BAY_INHERIT, b"")
    assert R.record(TRACK_LEFT_BAY, 5, b"") == bytes.fromhex("4c0500")
    print("  layer1 bay record encodes to 4c0500, matching the capture")


def test_the_new_config_keeps_every_field_the_template_had():
    """We model 4 of a Track's 15 fields. A config written from the DB alone would leave the
    module without motion axes -- the write must carry all 15."""
    layer1 = dict(BASE, **{"track:keyboard_left": TRACK_ALT})
    d, _ = _desired({0: BASE, 1: layer1})

    assert len(d.modules[5]) == 15, f"expected the full template, got {len(d.modules[5])} fields"
    # The four buttons carry the profile's bindings, as mouse-mask two-word records.
    for field, code in zip((0x0B, 0x0C, 0x0D, 0x0E), ("M1", "M3", "M2", "M4")):
        assert d.modules[5][field] == (R.TWO_WORD,
                                       R.encode_two_word(R.MOUSE_CATEGORY, R.MOUSE_MASK[code]))
    print("  15 fields written, 4 of them the profile's buttons")


def test_a_disabled_bay_is_written_as_zero():
    d, _ = _desired({0: dict(BASE, **{"tune:keyboard_left": "disabled"})})
    assert d.layers[0][0x4E] == (0, b"")
    print("  disabled bay -> (0, b'')")


def test_nothing_outside_the_bays_is_disturbed():
    """The layout must only touch positions 0x4a-0x51. A bay write that spilled into key
    positions would silently rebind keys."""
    layer1 = dict(BASE, **{"track:keyboard_left": TRACK_ALT})
    d, _ = _desired({0: BASE, 1: layer1, 2: {}})
    for order, poss in d.layers.items():
        outside = [p for p in poss if p not in F.MODULE_SLOT_POSITIONS]
        assert outside == [], f"layer {order} touched {outside}"
    print("  only positions 0x4a-0x51 were set")


def test_a_reflash_of_an_unchanged_layout_sends_no_module_writes():
    """Idempotence: the second flash of the same layout must be a no-op for modules, or every
    flash would rewrite slots that did not change."""
    d, _ = _desired({0: BASE, 1: {}, 2: {}})
    current = F.DesiredState()
    current.module_list = dict(d.module_list)
    current.layers = {i: dict(p) for i, p in d.layers.items()}

    ops = F.compute_plan(d, current, full=False)
    module_ops = [o for o in ops if o.sub in (R.WRITE_MODULE_CONFIG_DATA,
                                              R.WRITE_MODULE_CONFIG_LIST)]
    assert module_ops == [], [o.label for o in module_ops]
    print("  re-flashing an unchanged layout sends nothing")


def test_the_list_entry_carries_the_profiles_uuid_and_type():
    layer1 = dict(BASE, **{"track:keyboard_left": TRACK_ALT})
    d, _ = _desired({0: BASE, 1: layer1})
    lid, code, uuid16 = d.module_list[5]

    assert uuid16 == bytes.fromhex(TRACK_ALT.replace("-", ""))
    assert code == ml.MODULE_TYPE_CODE["TRACK"] == 1
    payload = R.encode_module_config_list([(5, lid, code, uuid16)])
    assert R.parse_module_config_list(payload)[0]["uuid"] == TRACK_ALT
    print("  list entry round-trips to the right uuid and type 1 (Track)")


# A capture is the config already sitting in a device slot, under a new app-side uuid. Without
# provenance the planner cannot tell, so it allocates a fresh slot and leaves the original
# stranded -- and because orphan GC needs a module read the flash does not have, the stranded
# entry never gets cleaned up. Every read->capture->flash cycle would leak a slot.
CAPTURE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _db_with_capture(bays_per_layer, captured_from=TRACK_R, edited=False):
    conn = _db(bays_per_layer)
    conn.execute("INSERT INTO module_configs VALUES (?,?,?,?)",
                 (CAPTURE, "Track R (on board)", "TRACK", captured_from))
    if edited:
        conn.execute("INSERT INTO module_bindings (module_config_id,behavior,action_code) VALUES (?,?,?)",
                     (CAPTURE, "tap:track:button_1", "M2"))
    conn.commit()
    return conn


def _desired_with_capture(bays_per_layer, **kw):
    d = F.DesiredState()
    d.profile_id = PID
    for order in bays_per_layer:
        d.layers[order], d.leds[order] = {}, {}
    conn = _db_with_capture(bays_per_layer, **kw)
    layout = F.apply_module_layout(d, conn, MOD_READ)
    conn.close()
    return d, layout


def test_a_capture_claims_the_slot_it_came_from_instead_of_stranding_it():
    bays = dict(BASE, **{"track:keyboard_right": CAPTURE})
    d, layout = _desired_with_capture({0: bays})

    assert layout["allocated"] == [], "claiming a slot must not allocate a new one"
    assert layout["claimed"] == [CAPTURE]
    assert layout["slot_for"][CAPTURE] == 1, "the slot Track Right occupies"
    assert TRACK_R not in layout["slot_for"], "the profile it drifted from is no longer referenced"
    assert sorted(d.module_list) == [1, 2, 3, 4], "still four slots, none leaked"
    print("  capture claimed slot 1; no slot allocated, none stranded")


def test_claiming_an_unchanged_slot_sends_no_config_data():
    """Only the list entry changes, to name the capture instead of the profile it drifted from.
    Rewriting identical bytes on every flash would be pure churn."""
    bays = dict(BASE, **{"track:keyboard_right": CAPTURE})
    d, _ = _desired_with_capture({0: bays})

    assert d.modules == {}, f"expected no config write, got slots {sorted(d.modules)}"
    ops = _ops(d)
    assert [o for o in ops if o.sub == R.WRITE_MODULE_CONFIG_DATA] == []
    assert len([o for o in ops if o.sub == R.WRITE_MODULE_CONFIG_LIST]) == 1
    print("  list entry only, zero config bytes")


def test_an_edited_capture_rewrites_the_slot_it_claims():
    """Claiming a slot is not the same as leaving it alone -- if the profile has since been
    edited, the slot must be brought in line."""
    bays = dict(BASE, **{"track:keyboard_right": CAPTURE})
    d, layout = _desired_with_capture({0: bays}, edited=True)

    assert layout["slot_for"][CAPTURE] == 1
    assert list(d.modules) == [1], "the claimed slot must be rewritten"
    assert d.modules[1][0x0B] == (R.TWO_WORD,
                                  R.encode_two_word(R.MOUSE_CATEGORY, R.MOUSE_MASK["M2"]))
    assert len(d.modules[1]) == 36, "templated from its own slot, keeping every field"
    print("  edited capture rewrote slot 1 with all 36 fields")


def test_the_original_keeps_its_slot_when_both_are_still_referenced():
    """Identity wins over provenance: if the profile a capture came from is itself in use, it
    owns its slot and the capture takes a fresh one."""
    bays = dict(BASE, **{"track:keyboard_right": TRACK_R})     # original still used on base
    layer1 = dict(BASE, **{"track:keyboard_right": CAPTURE})   # capture used on layer 1
    d, layout = _desired_with_capture({0: bays, 1: layer1})

    assert layout["slot_for"][TRACK_R] == 1
    assert layout["claimed"] == [] and layout["allocated"] == [CAPTURE]
    assert layout["slot_for"][CAPTURE] == 5
    print("  original kept slot 1; capture allocated slot 5")


def test_provenance_pointing_at_something_not_on_the_board_is_ignored():
    """A stale captured_from must not silently claim a slot that is not there."""
    bays = dict(BASE, **{"track:keyboard_right": CAPTURE})
    d, layout = _desired_with_capture({0: bays}, captured_from="dead-uuid-not-on-device")
    assert layout["claimed"] == [] and layout["allocated"] == [CAPTURE]
    print("  stale provenance ignored; fell back to allocation")


# --- axis gestures: two fields, splittable, invertible ---------------------- #
#
# Ground truth is the NayaFlow capture of 2026-09-03: splitting horizontal:track and binding the
# halves to 's' and 'g' produced exactly these two records, and on the device the -1 field fired
# on a leftward swipe.

def test_an_unsplit_axis_writes_the_two_direction_records():
    got = ml.encode_axis("TRACK", "horizontal:track", {})
    assert got[0x07] == (R.TWO_WORD, R.encode_two_word(0, -1))
    assert got[0x08] == (R.TWO_WORD, R.encode_two_word(0, +1))
    print("  0x07 sel -1, 0x08 sel +1")


def test_a_split_axis_writes_a_keypress_per_half_matching_the_capture():
    got = ml.encode_axis("TRACK", "horizontal:track", {"minus": "S", "plus": "G"})
    # The exact bytes NayaFlow sent: usage, page 7, no modifiers.
    assert got[0x07][1].hex() == "16000700", got[0x07][1].hex()
    assert got[0x08][1].hex() == "0a000700", got[0x08][1].hex()
    assert got[0x07][0] == R.KEY_PRESS and got[0x08][0] == R.KEY_PRESS
    print("  0x07='s' 16000700, 0x08='g' 0a000700 -- byte-identical to the capture")


def test_half_a_split_leaves_the_other_half_as_an_axis():
    """Binding one direction to a key must not silently kill motion in the other."""
    got = ml.encode_axis("TRACK", "horizontal:track", {"minus": "S"})
    assert got[0x07][0] == R.KEY_PRESS
    assert got[0x08] == (R.TWO_WORD, R.encode_two_word(0, +1))
    print("  one key, one axis half")


def test_invert_flips_both_selector_signs():
    """There is no invert flag anywhere in the config -- inverting IS writing the opposite signs.
    That is why NayaFlow's invert control does nothing: it never wrote anything at all."""
    got = ml.encode_axis("TRACK", "horizontal:track", {"invert": True})
    assert got[0x07] == (R.TWO_WORD, R.encode_two_word(0, +1))
    assert got[0x08] == (R.TWO_WORD, R.encode_two_word(0, -1))
    print("  signs swapped, no flag byte touched")


def test_invert_does_not_disturb_a_half_bound_to_a_key():
    got = ml.encode_axis("TRACK", "horizontal:track", {"minus": "S", "invert": True})
    assert got[0x07][1].hex() == "16000700", "the key stays put"
    assert got[0x08] == (R.TWO_WORD, R.encode_two_word(0, -1)), "the axis half inverts"
    print("  key half unchanged, axis half inverted")


def test_rotate_halves_are_not_in_field_order():
    """rotate:track stores +1 at 0x09 and -1 at 0x0a -- the reverse of the other pairs. Deriving
    the field from the sign would put both records in the wrong place."""
    got = ml.encode_axis("TRACK", "rotate:track", {})
    assert got[0x09] == (R.TWO_WORD, R.encode_two_word(4, +1))
    assert got[0x0A] == (R.TWO_WORD, R.encode_two_word(4, -1))
    print("  0x09 is the + half, 0x0a the - half")


def test_a_track_hold_binding_cannot_reach_the_device():
    """Capture 2026-09-03: NayaFlow wrote the hold value over the tap and the tap never arrived.
    Track has one field per button and no sixteenth field, so hold has nowhere to live."""
    from openflow_backend.device import module_fields as MF
    assert MF.gesture_has_device_field("TRACK", "tap:track:button_1")
    assert not MF.gesture_has_device_field("TRACK", "hold:track:button_1")
    # And it must not be silently written into the tap's field.
    cfg = ml.overlay({0x0B: (R.KEY_PRESS, b"\x00")}, "TRACK",
                     {"tap:track:button_1": "D", "hold:track:button_1": "A"})
    assert cfg[0x0B][1].hex() == "07000700", "the TAP must win the field, not the hold"
    print("  hold is unbacked; the tap keeps its field")


def test_a_profile_already_on_the_board_is_still_written_when_it_differs():
    """The bug this exists for. A slot already carrying the profile's uuid was marked "keep" and
    left completely alone, on the theory it must already be correct. It is not: an edit that
    never reached the board is exactly what a flash is for.

    The difference is a REAL one here -- the three-finger tap bound to a key. This test used to
    put M1 / M2 over an empty Touch slot and expect mask 1 / mask 2 written, which was the
    mistake it was pinning: on the Touch, EMPTY IS M1 / M2, done by the module firmware
    (module_fields.FIRMWARE_DEFAULTS, 2026-09-09), and those gestures are LOCKED -- a key on
    the one-finger tap below is written EMPTY over this fixture's junk, the other half of the
    same rule."""
    bays = dict(BASE, **{"touch:keyboard_left": TOUCH})
    conn = _db({0: bays})
    for g, code in (("tap:touch:3_fingers", "B"), ("tap:touch:1_finger", "B")):
        conn.execute("INSERT INTO module_bindings (module_config_id,behavior,action_code) "
                     "VALUES (?,?,?)", (TOUCH, g, code))
    conn.commit()
    d = F.DesiredState()
    d.profile_id = PID
    d.layers[0], d.leds[0] = {}, {}
    layout = F.apply_module_layout(d, conn, MOD_READ)
    conn.close()

    assert TOUCH in layout["kept"], "Touch is already on the board"
    slot = layout["slot_for"][TOUCH]
    assert slot in d.modules, "a kept slot that differs must still be written"
    from openflow_backend.device import module_fields as MF
    fields = MF.mouse_button_fields("TOUCH")
    assert d.modules[slot][fields["tap:touch:3_fingers"]] == (
        R.KEY_PRESS, R.encode_keypress("key", "B")), "the key must reach the field"
    assert d.modules[slot][fields["tap:touch:1_finger"]] == (R.NONE_BEH, b""), \
        "the one-finger tap is locked to the firmware: written empty, whatever the row says"
    print(f"  kept slot {slot} rewritten: three-finger tap -> B explicitly, one-finger tap -> empty (locked)")


def test_a_kept_touch_at_its_firmware_defaults_sends_nothing():
    """M1 / M2 over an EMPTY Touch slot is not a difference -- empty IS left / right click there.
    Until 2026-09-09 every flash wrote mask 1 / mask 2 into 0x0b / 0x0c for the stock profile."""
    from openflow_backend.device import module_fields as MF
    fields = MF.mouse_button_fields("TOUCH")
    read = {"by_uuid": dict(MOD_READ["by_uuid"]), "slots": dict(MOD_READ["slots"])}
    read["slots"][3] = [({"field": f["field"], "type": R.NONE_BEH, "value": ""}
                         if f["field"] in fields.values() and f["field"] != fields["tap:touch:3_fingers"]
                         else f) for f in MOD_READ["slots"][3]]
    bays = dict(BASE, **{"touch:keyboard_left": TOUCH})
    conn = _db({0: bays})
    for g, code in (("tap:touch:1_finger", "M1"), ("tap:touch:2_fingers", "M2")):
        conn.execute("INSERT INTO module_bindings (module_config_id,behavior,action_code) "
                     "VALUES (?,?,?)", (TOUCH, g, code))
    conn.commit()
    d = F.DesiredState()
    d.profile_id = PID
    d.layers[0], d.leds[0] = {}, {}
    layout = F.apply_module_layout(d, conn, read)
    conn.close()
    slot = layout["slot_for"][TOUCH]
    assert TOUCH in layout["kept"] and slot not in d.modules, \
        f"a Touch at its firmware defaults must send no config write, got {d.modules.get(slot)}"
    print("  M1 / M2 over an empty slot -> no difference, no write")


def test_a_kept_slot_that_matches_still_sends_nothing():
    """The other half: writing a slot back unchanged on every flash would be pure churn."""
    d, layout = _desired({0: BASE, 1: {}, 2: {}})
    assert set(layout["kept"]) == set(layout["slot_for"]), "all four are already on the board"
    assert d.modules == {}, f"unchanged profiles must send no data: {sorted(d.modules)}"
    print("  four kept slots, all matching, zero config writes")


def test_module_settings_reach_the_device():
    """set_module_setting stored a slider in the app and the overlay copied the DEVICE's own
    setting fields straight back, so every slider on the Modules page silently did nothing to
    the keyboard. Same shape as the Track hold and the modifier chords: it looked applied.

    The record format is read off a stock module, not invented: ONE byte with type 0x01 (the
    same type byte a keypress uses, at a different length). 0x00 = 0a is pointer speed 10.
    """
    from openflow_backend.device import module_layout as ml, remap as R, module_fields as MF

    template = {i: (R.KEY_PRESS, bytes([v])) for i, v in
                {0x00: 10, 0x01: 10, 0x02: 50, 0x03: 1, 0x06: 75, 0x07: 1}.items()}
    out = ml.overlay(dict(template), "TUNE", {}, {},
                     {"scroll_speed": "100", "pointer_speed": 25,
                      "toggle_ticks": "false", "tick_strength": 0})

    assert out[0x01] == (R.KEY_PRESS, bytes([100])), "scroll_speed -> 0x01, one byte"
    assert out[0x00] == (R.KEY_PRESS, bytes([25]))
    assert out[0x07] == (R.KEY_PRESS, bytes([0])), "a toggle is 1/0"
    assert out[0x06] == (R.KEY_PRESS, bytes([0])), "0 is a real value, not 'unset'"
    assert out[0x02] == template[0x02], "a setting not being changed is left alone"
    for _, val in out.values():
        assert len(val) == 1, "a settings field is one byte; four would be a keypress"
    print("  settings land in their fields as single bytes")


def test_a_setting_we_cannot_place_is_left_on_the_board():
    """Only settings whose device field is actually established get written. ticks_per_rotation
    is the one that is not: it was mapped to 0x05, but that defaults to 72 and bottoms out at 5
    while the device stores 5, and setting it to 100 made the detents softer and further apart
    -- so 0x05 reads as tick SPACING, not a count. Writing 72 there would be a guess the user
    feels in the dial."""
    from openflow_backend.device import module_layout as ml, remap as R, module_fields as MF

    template = {0x05: (R.KEY_PRESS, bytes([5]))}
    out = ml.overlay(dict(template), "TUNE", {}, {}, {"ticks_per_rotation": 72})
    assert out[0x05] == template[0x05], "0x05 must be left exactly as the board has it"
    assert not MF.setting_is_writable("TUNE", "ticks_per_rotation")
    assert MF.setting_is_writable("TUNE", "scroll_speed")
    assert "ticks_per_rotation" not in MF.setting_fields("TUNE")
    print("  an unplaceable setting changes nothing on the device")


def test_a_garbage_setting_value_cannot_corrupt_a_field():
    from openflow_backend.device import module_layout as ml, remap as R

    template = {0x01: (R.KEY_PRESS, bytes([10]))}
    for bad in ("", "fast", None, "12x"):
        out = ml.overlay(dict(template), "TUNE", {}, {}, {"scroll_speed": bad})
        assert out[0x01] == template[0x01], f"{bad!r} must leave the board's value"
    # ...and a value past a byte is clamped rather than wrapping to something unrelated.
    out = ml.overlay(dict(template), "TUNE", {}, {}, {"scroll_speed": 4000})
    assert out[0x01] == (R.KEY_PRESS, bytes([255]))
    print("  a bad value leaves the field alone; an out-of-range one clamps")
