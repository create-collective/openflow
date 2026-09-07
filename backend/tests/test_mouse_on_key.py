"""A mouse binding on a KEY position must reach the device.

Before this, `_binding_rows_to_record` returned None for actionType "mouse", so a mouse binding
saved to the DB, rendered on the board in the UI, and was silently never flashed -- the same
class of failure as the Track-hold and unresolvable-layer-switch bugs.

The encoding is measured, not assumed. tools/c9_key_record_probe.py wrote each candidate to
layer 0 position 46 and the key was pressed:

    0f 08 03000000 01000000   (module two-word form)  -> real left click
    0f 08 03000000 02000000                           -> real right click

so a key takes the SAME two-word record a module gesture does. The competing hypothesis was
ZMK's bare `&mkp` button bitmask, and it is not merely unsupported -- it is actively dangerous
to emit, because the device ACCEPTS a short param and reads it back verbatim while ignoring it:

    write 0f 08 03000000 02000000   -> key right-clicks
    write 0f 04 01000000            -> reads back as 01000000, key STILL right-clicks

A shortened param therefore produces a key that silently keeps its previous binding, which no
read-back or round-trip test would catch. That is why these tests assert the exact bytes rather
than just "something mouse-shaped was returned".
"""
from openflow_backend.device import flash as F
from openflow_backend.device import remap as R


def _rec(code):
    return F._binding_rows_to_record([{"beh": "press", "at": "mouse", "ac": code}], 200, 0, {})


def test_mouse_on_a_key_is_encoded_at_all():
    """The regression itself: this used to be None."""
    assert _rec("M1") is not None, "a mouse binding on a key is being dropped again"


def test_mouse_on_a_key_uses_the_module_two_word_form():
    typ, param = _rec("M1")
    assert typ == R.TWO_WORD, f"expected record type 0x0f, got {typ:#04x}"
    # Exactly the bytes that produced a left click on the board.
    assert param == bytes.fromhex("0300000001000000"), param.hex()


def test_each_button_encodes_to_its_own_mask():
    """A single shared mask would still 'work' for M1 and silently break every other button."""
    seen = {}
    for code in ("M1", "M2", "M3", "M4", "M5"):
        rec = _rec(code)
        assert rec is not None, f"{code} did not encode"
        seen[code] = rec[1]
    assert len(set(seen.values())) == 5, f"buttons collided: {[(k, v.hex()) for k, v in seen.items()]}"
    # M2 is the one confirmed on hardware besides M1 (it right-clicked).
    assert seen["M2"] == bytes.fromhex("0300000002000000"), seen["M2"].hex()


def test_an_unknown_button_is_not_flashed_as_something_else():
    """Must be dropped, not coerced -- writing a wrong mask would bind a real, wrong click."""
    assert _rec("M9") is None
    assert _rec("") is None
