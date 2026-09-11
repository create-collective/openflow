"""Every binding record on a real board decodes, re-encodes byte for byte, and is in the palette.

The capture is NayaFlow's own flash of its default profile plus the owner's edits
(device/out/after-a3-outputs-test-20260910.json), so it carries the record types a stock board
actually uses: keypresses, momentary / to / toggle / STICKY layer switches, the four Bluetooth
device selects and BT_CLEAR, the Wireless / USB-C output selectors, the fourteen LED system keys
and Naya's own MODULE_FORCE_CHARGING. On 2026-09-10 the backlog still called three of those
"no encoder" or "never read off a device"; this test is what says otherwise, per record.

Bay positions 0x4A-0x51 are excluded: their type byte is a module SLOT number and the module
layout owns them. Hold-tap records are excluded: they carry the tapping term and flavour inside
the param and test_four_behaviour_roundtrip.py covers them. No hardware.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as AC   # noqa: E402
from openflow_backend.device import flash as F              # noqa: E402
from openflow_backend.device import keymap_read as K        # noqa: E402
from openflow_backend.device import remap as R              # noqa: E402

# The repo root is wherever `device/` lives: two levels up in NayaOS, one in the OpenFlow repo.
_REPO = next(p for p in _BACKEND.parents if (p / "device").is_dir())
CAPTURE = _REPO / "device" / "out" / "after-a3-outputs-test-20260910.json"
ORDER_TO_LAYER = {0: "L0", 1: "L1", 2: "L2"}
LAYER_ORDER = {"L0": 0, "L1": 1, "L2": 2}
BAYS = set(range(0x4A, 0x52))
# NONE and TRANSPARENT translate to no binding row on purpose: an unset position keeps the
# device's own record through a sync flash (_full_layer_payload fills from the read). Their
# explicit encodings are checked on their own below.
SKIP_TYPES = {R.NONE_BEH, R.TRANS, *K.HOLD_TAP_TYPES}
# Record type byte -> what it is, so a failure names the feature and not a number.
NAMES = {0x00: "bluetooth", 0x01: "key_press", 0x05: "MO layer", 0x06: "naya system",
         0x08: "outputs", 0x09: "LED system", 0x0B: "sticky layer", 0x0C: "TO layer",
         0x0D: "toggle layer", 0x0E: "transparent", 0x0F: "mouse"}


def _records():
    if not CAPTURE.exists():
        pytest.skip(f"{CAPTURE.name} not on disk")
    layers = json.loads(CAPTURE.read_text(encoding="utf-8"))["keymap"]["layers"]
    for li, recs in layers.items():
        for pos, typ, param in recs:
            if pos in BAYS or typ in SKIP_TYPES:
                continue
            yield int(li), pos, typ, bytes.fromhex(param)


def _roundtrip(typ, param):
    acts = K.translate(typ, param, ORDER_TO_LAYER)
    if not acts:
        return None, acts
    rows = [{"beh": beh, "at": at, "ac": code} for beh, at, code in acts]
    return F._binding_rows_to_record(rows, 200, 0, LAYER_ORDER), acts


def test_every_record_on_the_board_survives_decode_then_encode():
    seen, failures = Counter(), []
    for li, pos, typ, param in _records():
        got, acts = _roundtrip(typ, param)
        seen[typ] += 1
        if got != (typ, param):
            failures.append(f"L{li} pos {pos:#04x} {NAMES.get(typ, hex(typ))}: "
                            f"{typ:#04x} {param.hex()} -> {acts} -> {got}")
    assert not failures, "\n".join(failures)
    print("  round-tripped per type:", {NAMES.get(t, hex(t)): n for t, n in sorted(seen.items())})


@pytest.mark.parametrize("typ, at_least, what", [
    (0x0B, 4, "sticky layer (positions 53/54 on layers 1 and 2)"),
    (0x06, 1, "MODULE_FORCE_CHARGING (layer 2 position 62)"),
    (0x00, 10, "bluetooth: BT_DEVICE_1..4 on both halves plus BT_CLEAR twice"),
    (0x08, 4, "outputs: BT_OUT and USB_DEVICE on both halves"),
    (0x09, 14, "the LED system keys"),
    (0x05, 6, "MO layer"),
    (0x0C, 7, "TO layer"),
])
def test_the_types_the_backlog_doubted_are_really_on_this_board(typ, at_least, what):
    """The claim is only worth something if the capture actually contains the records."""
    n = sum(1 for _li, _pos, t, _p in _records() if t == typ)
    assert n >= at_least, f"expected at least {at_least} x {what}, capture has {n}"


def test_transparent_and_disabled_have_explicit_encodings_too():
    """A user CAN choose Transparent or Disabled in the palette; those rows must reach the wire
    as 0x0e / 0x07 with an empty param, which is what recovery mode relies on."""
    assert F._binding_rows_to_record([{"beh": "press", "at": "trans", "ac": "TRANS"}], 200, 0, LAYER_ORDER) == (R.TRANS, b"")
    assert F._binding_rows_to_record([{"beh": "press", "at": "none", "ac": "DISABLE"}], 200, 0, LAYER_ORDER) == (R.NONE_BEH, b"")


def test_bt_clear_is_a_real_record_not_none():
    """The old backlog note said BT_CLEAR reads back as NONE on a stock board. It does not."""
    clears = [(li, pos) for li, pos, typ, param in _records()
              if typ == 0x00 and K.translate(typ, param, ORDER_TO_LAYER) == [("press", "bluetooth", "BT_CLEAR")]]
    assert (2, 6) in clears and (2, 73) in clears, clears


def test_every_decoded_action_is_in_the_palette():
    """What the board holds must be something the UI can show and bind, not only re-emit."""
    codes = set()

    def walk(o):
        if isinstance(o, dict):
            if "code" in o and "label" in o:
                codes.add(o["code"])
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(AC.get_catalog())

    missing = set()
    for _li, _pos, typ, param in _records():
        for _beh, at, code in K.translate(typ, param, ORDER_TO_LAYER):
            if at.startswith("layer_") or at in ("trans", "none"):
                continue           # dynamic per-profile targets / structural, not palette entries
            if at in R.CHORD_ACTION_TYPES:
                # A chord is composed from palette keys, not a palette entry itself: every
                # token must be one.
                for tok in code.split(" + "):
                    if tok not in codes:
                        missing.add((at, code, tok))
                continue
            if code not in codes:
                missing.add((at, code))
    assert not missing, sorted(missing)
