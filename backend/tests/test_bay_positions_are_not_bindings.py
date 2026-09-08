"""A module bay is not a key binding, and reading it as one invented bindings on every import.

THE BUG. `decode_keymap` ran `translate()` over every record in a layer, module bays included.
At positions 0x4A-0x51 the record's "type" byte is the module-config SLOT NUMBER, not a
behaviour type -- `decode_bays` reads exactly that byte to resolve which config a bay holds. So
the slot number was fed to the behaviour table:

    slot 0 -> two-param / bluetooth        slot 3 -> mod_tap
    slot 1 -> KEY_PRESS                    slot 5 -> layer hold, with no target
    slot 2 -> macro

Every read therefore imported up to eight invented bindings per layer. Slots 1, 2 and 3 produced
bindings that looked entirely ordinary and nothing flagged them. Only slot 5 was visible, because
a layer hold needs a target layer and there wasn't one -- it became `MO_LAYER_-1`, which then
showed up in a flash preview as "OpenFlow has no encoder for action type 'layer_polite_hold'".
That drop report is what finally exposed it; the silent ones had been accumulating for weeks.

This is the same shape as the 0x08/LAYER_SW bug: a byte read through the wrong table producing a
plausible answer. The bytes below are the real bays from the reference board
(device/out/before-layer-list-resync.json), which is what makes this a regression test rather
than a restatement of the fix.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr    # noqa: E402

# Layer 0 of the reference board: eight bays holding slots 1,1,2,3,5,5,0,0.
REAL_BAYS = [(0x4A, 0x01, b""), (0x4B, 0x01, b""), (0x4C, 0x02, b""), (0x4D, 0x03, b""),
             (0x4E, 0x05, b""), (0x4F, 0x05, b""), (0x50, 0x00, b""), (0x51, 0x00, b"")]

A_REAL_KEY = (0x05, kr.KEY_PRESS, bytes.fromhex("04000700"))     # position 5 types 'A'


def decode(recs):
    return kr.decode_keymap({"layers": {0: recs}, "led": {}}, {0: "layer-uuid-0"})


def test_the_bay_range_matches_the_flash_side():
    from openflow_backend.device import flash as F
    assert list(kr.BAY_POSITIONS) == list(F.MODULE_SLOT_POSITIONS) == list(range(0x4A, 0x52))


def test_no_bay_produces_a_binding():
    """The whole fix, against the board's own bytes."""
    out = decode(REAL_BAYS)
    assert out[0] == {}, out[0]


def test_every_slot_number_that_collides_with_a_behaviour_type_is_covered():
    """Not just slot 5. Slots 1/2/3 were the dangerous ones because they looked legitimate."""
    for slot in range(0, 0x10):
        out = decode([(0x4A, slot, b"")])
        assert out[0] == {}, f"slot {slot} still decoded to {out[0]}"


def test_the_specific_mo_layer_minus_one_that_exposed_this():
    """Slot 5 -> LAYER_HOLD with no resolvable target -> 'MO_LAYER_-1', the entry that appeared
    in the flash preview as unencodable."""
    out = decode([(0x4E, 0x05, b"")])
    assert out[0] == {}
    # And prove the old path really did produce it, so this test cannot pass vacuously.
    assert any("-1" in str(code) for _b, _at, code in kr.translate(0x05, b"", {0: "u"})), \
        "translate no longer yields MO_LAYER_-1; this test's premise needs rechecking"


def test_real_keys_are_still_imported():
    """The fix must not be 'skip more records'. A binding either side of the bay range survives."""
    out = decode([A_REAL_KEY] + REAL_BAYS)
    assert 0x05 in out[0], out[0]
    assert out[0][0x05][0][2] == "A"


def test_a_second_bank_binding_is_not_caught_by_the_bay_filter():
    """The second bank starts at 0x52, just past the bays. Filtering raw positions must not eat
    a double-tap -- 0x4A+0x52 = 0x9C is outside the bank, but the boundary is worth pinning."""
    out = decode([(0x52 + 0x05, kr.KEY_PRESS, bytes.fromhex("05000700"))])
    assert 0x05 in out[0], out[0]
    assert out[0][0x05][0][0] == "double_tap"


def test_bays_are_still_decoded_by_the_path_that_understands_them():
    """Skipping them in the binding loop must not lose them: decode_bays reads the same byte as
    a slot number, which is what it actually is."""
    bays = kr.decode_bays(REAL_BAYS)
    assert bays, "bays vanished entirely"
    # Keyed by dock location, and slot 0 reads as 'disabled' (an empty bay) rather than slot 0.
    assert set(bays) == {"touch:keyboard_left", "touch:keyboard_right",
                         "track:keyboard_left", "track:keyboard_right",
                         "tune:keyboard_left", "tune:keyboard_right",
                         "float:keyboard_left", "float:keyboard_right"}, sorted(bays)
    assert set(bays.values()) <= {1, 2, 3, 5, "disabled"}, bays
