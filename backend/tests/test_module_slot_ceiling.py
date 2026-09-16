"""A full module store is garbage-collected as far as needed, and never blocks a flash.

keymap_read.read_module_configs reads slots 0-7 (NayaCore's ModuleConfig::maxSlots is not yet
recovered, so that range is the working ceiling). When no index is free, the planner reuses the
slots of module profiles the keyboard profile does not reference, lowest first, and reports
them as reclaimed; the preview shows which. What sits on the board must not block a flash of
what the user chose (owner, 2026-09-16, after a refusal did exactly that). The only refusal
left is a profile arming more distinct module profiles than the store holds. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

import uuid                                                    # noqa: E402

import pytest                                                  # noqa: E402
from openflow_backend.device import module_layout as ml, remap as R   # noqa: E402


# Real uuids: the planner encodes a config id as its 16 bytes for the list entry.
U = {i: str(uuid.uuid4()) for i in range(1, 8)}
NEW = {k: str(uuid.uuid4()) for k in ("new1", "new2", "new3")}


def _board(n):
    """A module list with slots 1..n taken, all Track."""
    return [{"uuid": U[i], "slot": i, "type": "TRACK"} for i in range(1, n + 1)]


def _slots(n):
    """Slot contents for slots 1..n: a clean 15-field Track each, so a new config can be
    templated from one of them (the planner refuses otherwise)."""
    return {i: {f: (R.KEY_PRESS, b"") for f in range(15)} for i in range(1, n + 1)}


def test_free_slots_first_then_orphans_are_reclaimed_lowest_first():
    types = {U[i]: "TRACK" for i in range(1, 8)}
    types.update({NEW[k]: "TRACK" for k in NEW})
    # Five taken, two more wanted: slots 6 and 7 are free and get used; nothing reclaimed.
    bays = {0: {"track:keyboard_left": NEW["new1"], "track:keyboard_right": NEW["new2"]}}
    out = ml.plan(bays, types, _board(5), _slots(5), base_order=0)
    assert sorted(out["slot_for"][NEW[c]] for c in ("new1", "new2")) == [6, 7]
    assert out["reclaimed"] == {}
    # The 2026-09-16 case: five taken, the profile references three of them and arms three
    # new ones. 6 and 7 are free; the third takes over the lowest slot this profile does not
    # reference (2, not 5), and the plan says so. Nothing is refused.
    bays = {0: {"track:keyboard_left": U[1], "track:keyboard_right": U[3],
                "tune:keyboard_left": U[4],
                "touch:keyboard_left": NEW["new1"], "touch:keyboard_right": NEW["new2"],
                "tune:keyboard_right": NEW["new3"]}}
    out = ml.plan(bays, types, _board(5), _slots(5), base_order=0)
    got = {c: out["slot_for"][NEW[c]] for c in NEW}
    assert sorted(got.values()) == [2, 6, 7], got
    assert out["reclaimed"] == {2: U[2]}, out["reclaimed"]
    assert all(NEW[c] in out["allocated"] for c in NEW), "a reclaimed slot is written like a new one"
    assert set(s for s, _l, _c, _u in out["list_entries"]) == {1, 2, 3, 4, 6, 7}, "the list names the new profile at slot 2; slot 5 stays an orphan"
    print("  free 6 and 7 first, then slot 2 reclaimed from the unreferenced profile; slot 5 left")


def test_only_more_distinct_profiles_than_the_store_holds_is_refused():
    types = {U[i]: "TRACK" for i in range(1, 8)}
    types.update({NEW[k]: "TRACK" for k in NEW})
    # All five on the board referenced plus three new: eight distinct profiles, seven slots.
    bays = {0: {"track:keyboard_left": U[1], "track:keyboard_right": U[2],
                "tune:keyboard_left": U[3], "tune:keyboard_right": U[4],
                "touch:keyboard_left": U[5], "touch:keyboard_right": NEW["new1"],
                "float:keyboard_left": NEW["new2"], "float:keyboard_right": NEW["new3"]}}
    with pytest.raises(ValueError) as e:
        ml.plan(bays, types, _board(5), _slots(5), base_order=0)
    assert "8 distinct" in str(e.value) and "holds 7" in str(e.value)
    assert ml.MAX_MODULE_SLOTS == 8
    print("  eight distinct profiles on a seven-slot store is the one thing refused")
