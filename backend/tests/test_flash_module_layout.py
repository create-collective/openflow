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
        CREATE TABLE module_bindings (module_config_id TEXT, behavior TEXT, action_code TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT,
                                             module_config_id TEXT, binding_location TEXT,
                                             state TEXT);
    """)
    for cid, (name, typ) in NAMES.items():
        conn.execute("INSERT INTO module_configs VALUES (?,?,?,NULL)", (cid, name, typ))
    for i, code in zip((1, 2, 3, 4), ("M1", "M3", "M2", "M4")):
        conn.execute("INSERT INTO module_bindings VALUES (?,?,?)",
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
        conn.execute("INSERT INTO module_bindings VALUES (?,?,?)",
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
