"""The planner never allocates a module slot our own reader cannot read back.

keymap_read.read_module_configs reads slots 0-7. A plan that allocated slot 8 (2026-09-16: a
profile arming three configs the board did not carry, on a board with slots 1-5 taken) would
have written a config nobody could read again. NayaCore's ModuleConfig::maxSlots is not yet
recovered, so past the reader's range the planner refuses with a message the preview shows.
No hardware.
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


def test_seven_slots_is_the_ceiling():
    types = {U[i]: "TRACK" for i in range(1, 8)}
    types.update({NEW[k]: "TRACK" for k in NEW})
    # Five taken, two more wanted: slots 6 and 7 are allocated.
    bays = {0: {"track:keyboard_left": NEW["new1"], "track:keyboard_right": NEW["new2"]}}
    out = ml.plan(bays, types, _board(5), _slots(5), base_order=0)
    assert sorted(out["slot_for"][NEW[c]] for c in ("new1", "new2")) == [6, 7]
    # Five taken, three more wanted: the third would be slot 8, which nothing reads back.
    bays = {0: {"track:keyboard_left": NEW["new1"], "track:keyboard_right": NEW["new2"],
                "touch:keyboard_left": NEW["new3"]}}
    with pytest.raises(ValueError) as e:
        ml.plan(bays, types, _board(5), _slots(5), base_order=0)
    assert "no free module slot" in str(e.value) and "1-7" in str(e.value)
    assert ml.MAX_MODULE_SLOTS == 8
    print("  slots 6 and 7 are allocated; slot 8 is refused with a reason")
