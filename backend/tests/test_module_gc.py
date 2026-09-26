"""Garbage collecting module profiles during a full flash.

The removal order is NayaFlow's own, captured 2026-09-03: point the bays away, delete the list
entry, blank the slot. Order matters -- nothing should reference a slot while it is being
emptied -- and blanking must be FULL length, because a short write is exactly what left slot 1
holding a previous module's 21-field tail.

The safety property that matters most here is the opt-in: desired.module_list is None unless the
app is actually managing the module set, and while it is None NOTHING is collected. Without
that, today's empty desired.modules would make every config on the board look like an orphan.
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

UUID_A = bytes(range(16))
UUID_B = bytes(range(16, 32))


def _device(slots, bays=None):
    d = F.DesiredState()
    d.modules = {s: {0x00: (0x01, bytes([10]))} for s in slots}
    d.module_list = {s: (s, 1, UUID_A) for s in slots}
    d.layers = {0: dict(bays or {})}
    return d


def _wanted(slots, bays=None):
    d = F.DesiredState()
    d.modules = {s: {0x00: (0x01, bytes([10]))} for s in slots}
    d.module_list = {s: (s, 1, UUID_A) for s in slots}
    d.layers = {0: dict(bays or {})}
    return d


def _labels(plan):
    return [op.label for op in plan]


def test_nothing_is_collected_unless_the_app_manages_modules():
    """The critical guard: desired.module_list is None today, and every config on the board
    would otherwise look unwanted."""
    current = _device([1, 2, 3, 4])
    desired = F.DesiredState(layers={0: {}})          # module_list stays None
    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    assert not any("blank" in l or "drop" in l for l in _labels(plan)), _labels(plan)
    print("  module_list=None -> no slot is blanked and no list entry dropped")


def test_an_orphan_is_dropped_then_blanked_in_that_order():
    current = _device([1, 2, 5])
    desired = _wanted([1, 2])
    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    labels = _labels(plan)
    drop = next(i for i, l in enumerate(labels) if l == "drop module list entry 5")
    blank = next(i for i, l in enumerate(labels) if l == "blank module slot 5")
    assert drop < blank, "the slot was blanked before its list entry was removed"
    blank_op = plan[blank]
    recs = list(kr.parse_records(blank_op.payload[1:]))
    assert len(recs) == R.MODULE_SLOT_FIELDS, "blank must be a FULL-length write"
    assert all(t == 0 and not v for _f, t, v in recs)
    print(f"  slot 5: list entry dropped, then blanked with {len(recs)} type-0 records")


def test_bays_pointing_at_an_orphan_are_disabled_first():
    """A dangling bay reference is the corruption this exists to prevent."""
    bays = {0x4C: (5, b""), 0x4D: (1, b"")}
    current = _device([1, 5], bays)
    desired = _wanted([1], bays)
    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    layer = next(op for op in plan if op.sub == R.WRITE_LAYER_DATA)
    written = {p: t for p, t, v in kr.parse_records(layer.payload[1:])}
    assert written[0x4C] == 0, "a bay still points at the slot being blanked"
    assert written[0x4D] == 1, "an unrelated bay was disturbed"
    # and the layer write must come before the blank
    labels = _labels(plan)
    assert labels.index("layer 0") < labels.index("blank module slot 5")
    print("  bay 0x4c -> 0 (disabled) before the slot is emptied; 0x4d untouched")


def test_kept_slots_are_not_touched_by_collection():
    current = _device([1, 2, 5])
    desired = _wanted([1, 2])
    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    for slot in (1, 2):
        assert f"blank module slot {slot}" not in _labels(plan)
        assert f"drop module list entry {slot}" not in _labels(plan)
    print("  slots the app still wants are neither dropped nor blanked")


def test_the_list_is_rewritten_with_what_remains():
    current = _device([1, 5])
    desired = _wanted([1])
    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    lst = next(op for op in plan if op.sub == R.WRITE_MODULE_CONFIG_LIST
               and not op.label.startswith("drop"))
    entries = R.parse_module_config_list(lst.payload)
    assert [e["slot"] for e in entries] == [1], entries
    print("  the surviving list is written explicitly, not left to the incremental merge")


if __name__ == "__main__":
    for fn in (test_nothing_is_collected_unless_the_app_manages_modules,
               test_an_orphan_is_dropped_then_blanked_in_that_order,
               test_bays_pointing_at_an_orphan_are_disabled_first,
               test_kept_slots_are_not_touched_by_collection,
               test_the_list_is_rewritten_with_what_remains):
        print(fn.__name__)
        fn()
    print("\nOK")


def test_a_full_flash_does_not_collect_orphans_on_its_own():
    """Collecting is now asked for explicitly rather than implied by `full`.

    Deleting a module config is the one destructive thing a flash can do -- it drops a list
    entry and blanks a slot -- and a routine "write everything" should not decide to do it. The
    old gate also included `full`, which meant the normal flash (full=False) never collected at
    all, so this has never actually run against a board.
    """
    current, desired = _device([1, 2, 5]), _wanted([1, 2])
    plan = F.compute_plan(desired, current, full=True)
    labels = [op.label for op in plan]
    assert not any("drop module list entry" in l or "blank module slot" in l for l in labels), labels

    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    labels = [op.label for op in plan]
    assert any("drop module list entry" in l for l in labels), labels
    print("  full alone collects nothing; collect_orphans=True does")


def test_orphans_are_found_from_the_device_slots_not_from_a_keymap_read():
    """`current` is built from a KEYMAP read, whose `.modules` is empty. So collecting from
    `current.modules` found nothing every time -- the reason this never removed anything even
    when it was wired to `full`. The slots the board really holds have to be passed in."""
    current, desired = _device([1, 2, 5]), _wanted([1, 2])
    orphan_slots = set(current.modules)
    current.modules = {}                     # what a keymap read actually gives us

    plan = F.compute_plan(desired, current, full=True, collect_orphans=True)
    assert not any("blank module slot" in op.label for op in plan), \
        "with no device slots there is nothing to collect, and guessing would be worse"

    plan = F.compute_plan(desired, current, full=True, collect_orphans=True,
                          device_slots=orphan_slots)
    assert any("blank module slot" in op.label for op in plan), \
        "given the real slots, the orphan is found"
    print("  orphans come from the module read, not from the (empty) keymap one")


def test_a_flash_collects_unused_slots_unless_told_not_to():
    """On by default since 2026-09-26, as NayaFlow does it. The dialog's opt-in box was left
    unticked by testers, so every stale slot kept being read back and captured as a profile."""
    from openflow_backend.api import rest
    assert rest._collects_orphans({}) is True
    assert rest._collects_orphans({"collectOrphans": True}) is True
    assert rest._collects_orphans({"collectOrphans": False}) is False
