"""Record type 0x08 is `outputs`, not a layer switch.

THE BUG THIS PINS, and it is the worst one this project has found. `keymap_read` named 0x08
LAYER_SW and decoded it as `layer_rude_toggle / TO_LAYER_<n>`. It is ZMK's `&out`. So reading a
stock board turned the Bluetooth-output key into "Force Layer 2" and the USB-C key into "Force
Layer 1" -- and because the app then re-encodes what it read, the next flash wrote those back as
genuine `to_layer` records. A read-then-reflash round trip, which this app invites on every
profile, DESTROYED both keys.

It is not the usual "saves but never reaches the keyboard" failure. It silently replaced a
working key with a different working key.

Why it survived a byte-level round-trip test: an output selector and a layer index are both u32
little-endian, so re-encoding produced identical bytes. The test agreed with itself while the
meaning was wrong. Only the evidence below settles it.

EVIDENCE, three independent lines:
  * NayaCore's behaviour-type table (docs/reference/nayacore-vocabulary.json), whose index IS the
    record type byte, has 8 = "outputs" -- and already carried a note that our name was wrong.
  * The stock board read of 2026-09-01, device/run-20260901-013431/left-keymap-decoded.json,
    contains exactly two type-0x08 records, both on layer 2, at adjacent positions:
        idx 0x2f  param 02000000
        idx 0x30  param 01000000
  * NayaFlow's own database has BT_OUT at position 0x2f and USB_DEVICE at 0x30 in that profile.

So the param is a u32 LE selector: 1 = USB, 2 = wireless.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr    # noqa: E402
from openflow_backend.device import remap as R           # noqa: E402

STOCK_READ = _REPO / "device" / "run-20260901-013431" / "left-keymap-decoded.json"


def test_the_type_byte_is_named_for_what_it_is():
    assert R.OUTPUTS == 0x08
    assert not hasattr(R, "LAYER_SW"), "the old name must not linger as an alias"


def test_wireless_and_usb_decode_to_output_actions():
    assert kr.translate(0x08, bytes.fromhex("02000000"), {}) == [("press", "out", "BT_OUT")]
    assert kr.translate(0x08, bytes.fromhex("01000000"), {}) == [("press", "out", "USB_DEVICE")]


def test_it_is_not_decoded_as_a_layer_switch():
    """The specific regression: this used to return layer_rude_toggle / TO_LAYER_2."""
    for param in ("01000000", "02000000"):
        got = kr.translate(0x08, bytes.fromhex(param), {})
        kinds = {b for _slot, b, _code in got}
        assert "layer_rude_toggle" not in kinds, got
        assert not any((c or "").startswith("TO_LAYER_") for _s, _b, c in got), got


def test_an_unknown_selector_is_not_rounded_to_a_known_one():
    """Guessing is what produced the original bug. An unrecognised selector decodes to nothing
    rather than to whichever output happens to be closest."""
    assert kr.translate(0x08, bytes.fromhex("09000000"), {}) == []
    assert kr.translate(0x08, b"", {}) == []
    assert kr.translate(0x08, b"\x01", {}) == []          # too short to hold a selector


def test_against_the_real_stock_board_read():
    """The captured evidence itself, so this cannot drift back on someone's say-so."""
    if not STOCK_READ.is_file():
        import pytest
        pytest.skip(f"stock read not present: {STOCK_READ}")
    layers = json.loads(STOCK_READ.read_text(encoding="utf-8"))
    found = {}
    for entries in layers.values():
        for e in entries:
            if e.get("type") == 0x08:
                found[e["idx"]] = e["decoded"]
    assert found == {0x2F: "t0x8[02000000]", 0x30: "t0x8[01000000]"}, found
    # And those two bytes must now read as the outputs NayaFlow's database says they are.
    assert kr.translate(0x08, bytes.fromhex("02000000"), {})[0][2] == "BT_OUT"
    assert kr.translate(0x08, bytes.fromhex("01000000"), {})[0][2] == "USB_DEVICE"
