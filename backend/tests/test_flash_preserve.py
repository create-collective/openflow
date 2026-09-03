"""A full flash must not destroy state the app does not model, and must clean state it does.

Two failure modes, both observed on real hardware rather than imagined:

1. Layer positions 0x4A-0x51 hold the module->dock bindings (layer 0 on the reference board:
   0x4c -> slot 4 Track Left, 0x4d -> slot 1 Track Right). desired_from_db does not model them,
   so a full layer write that defaults absent positions to NONE would unassign every module.
2. Writing N module fields does not delete fields N+1..M. That is how the reference board ended
   up with a 15-field Track config carrying 21 orphaned Touch fields. A full write has to clear
   the difference explicitly.
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

# What layer 0 actually looks like on the reference board.
DEVICE_MODULE_SLOTS = {0x4A: 3, 0x4B: 3, 0x4C: 4, 0x4D: 1, 0x4E: 2, 0x4F: 2, 0x50: 0, 0x51: 0}


def _device_layer():
    layer = {0x00: (R.KEY_PRESS, R.encode_keypress("key", "A"))}
    layer.update({pos: (slot, b"") for pos, slot in DEVICE_MODULE_SLOTS.items()})
    return layer


def test_full_layer_write_carries_module_bindings_through():
    device = F.DesiredState(layers={0: _device_layer()})
    # the app models only the key, exactly as desired_from_db does
    desired = F.DesiredState(layers={0: {0x00: (R.KEY_PRESS, R.encode_keypress("key", "B"))}})

    plan = F.compute_plan(desired, device, full=True)
    payload = next(op.payload for op in plan if op.sub == R.WRITE_LAYER_DATA)
    written = {p: t for p, t, v in kr.parse_records(payload[1:])}

    for pos, slot in DEVICE_MODULE_SLOTS.items():
        assert written[pos] == slot, (
            f"module binding at {pos:#04x} became {written[pos]} instead of {slot} -- "
            "a full flash would unassign this module")
    assert written[0x00] == R.KEY_PRESS, "the key the app does model must still be written"
    print(f"  all {len(DEVICE_MODULE_SLOTS)} module->dock bindings survive a full layer write")


def test_full_layer_write_without_a_read_does_not_invent_bindings():
    """With no device read there is nothing to preserve; absent positions are NONE. This is
    why a full flash must require a fresh read first."""
    desired = F.DesiredState(layers={0: {0x00: (R.KEY_PRESS, R.encode_keypress("key", "B"))}})
    payload = next(op.payload for op in F.compute_plan(desired, None, full=True)
                   if op.sub == R.WRITE_LAYER_DATA)
    written = {p: t for p, t, v in kr.parse_records(payload[1:])}
    assert all(written[p] == R.NONE_BEH for p in DEVICE_MODULE_SLOTS), \
        "without a read the module positions are unknown and must not be guessed"
    print("  with no read, module positions are NONE -- read-before-full-flash is mandatory")


def test_full_module_write_clears_stale_trailing_fields():
    """The Track-Right-with-a-Touch-tail case: 36 fields on the device, 15 wanted."""
    device_fields = {f: (0x01, bytes([f])) for f in range(0x00, 0x24)}      # 36 fields
    want = {f: (0x01, bytes([f])) for f in range(0x00, 0x0F)}               # 15 fields
    device = F.DesiredState(modules={4: device_fields})
    desired = F.DesiredState(modules={4: want})

    payload = next(op.payload for op in F.compute_plan(desired, device, full=True)
                   if op.sub == R.WRITE_MODULE_CONFIG_DATA)
    recs = {f: (t, v) for f, t, v in kr.parse_records(payload[1:])}
    assert set(recs) == set(device_fields), "every device field must be addressed"
    for f in range(0x0F, 0x24):
        assert recs[f] == (R.NONE_BEH, b""), f"stale field {f:#04x} was not cleared"
    for f in range(0x00, 0x0F):
        assert recs[f][0] == 0x01, f"wanted field {f:#04x} was clobbered"
    print(f"  {len(device_fields) - len(want)} stale fields explicitly cleared, {len(want)} kept")


def test_partial_module_write_leaves_stale_alone():
    """A partial flash is not allowed to delete anything -- only a full one cleans."""
    device = F.DesiredState(modules={4: {f: (0x01, bytes([f])) for f in range(0x00, 0x24)}})
    desired = F.DesiredState(modules={4: {f: (0x01, bytes([f])) for f in range(0x00, 0x0F)}})
    payload = next(op.payload for op in F.compute_plan(desired, device, full=False)
                   if op.sub == R.WRITE_MODULE_CONFIG_DATA)
    recs = {f for f, t, v in kr.parse_records(payload[1:])}
    assert recs == set(range(0x00, 0x0F)), "a partial write must not touch fields it does not set"
    print("  partial write addresses only the wanted fields")


if __name__ == "__main__":
    for fn in (test_full_layer_write_carries_module_bindings_through,
               test_full_layer_write_without_a_read_does_not_invent_bindings,
               test_full_module_write_clears_stale_trailing_fields,
               test_partial_module_write_leaves_stale_alone):
        print(fn.__name__)
        fn()
    print("\nOK")
