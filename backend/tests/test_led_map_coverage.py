"""A flash must write the whole LED map, not just the part the binding code cares about.

THE BUG. `desired_from_db` collected key colours inside a loop guarded by

    if r["p"] is None or r["p"] not in FULL_LAYER_POSITIONS:   # range(0x00, 0x52) -> 0..81
        continue

That guard belongs to BINDINGS. Layer records stop at 0x51, but LED positions are a different
domain entirely: the DB models 97 key positions and the board reports 136 LEDs per layer. So
colours for positions 82-96 were discarded before they were ever seen, and `_led_payload` then
sized its write from the highest colour it had -- 81. A flash wrote LEDs 0-81 and left the other
54 holding whatever the last application to write them chose.

Reported from hardware as "the module LEDs stayed green rather than purple": every key LED took
the new profile while the module LEDs kept NayaFlow's colours through an OpenFlow flash.

TWO SEPARATE FIXES, and they are separate on purpose:
  * colour collection is no longer gated by the binding range -> 97 colours, not 82;
  * the write spans the whole map the DEVICE reports (136), with any LED the app has no model
    for passed through UNCHANGED from the device rather than defaulted. Writing a default into
    97-135 would replace one wrong colour with another and destroy whatever the modules are
    meant to show -- see docs/backlog.md.

For scale: NayaFlow's own captured LED write is 242/242/63 bytes, which is 1 + 136x4 plus the
per-continuation index byte. 545 is the number to match.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F          # noqa: E402
from openflow_backend.device import keymap_read as kr   # noqa: E402

UNSET = (0, kr.UNSET_SATURATION)


def leds(payload: bytes):
    """LED map payload -> {index: (hue, saturation)}."""
    body = payload[1:]
    return {body[i]: (body[i + 1] | (body[i + 2] << 8), body[i + 3])
            for i in range(0, len(body), 4)}


def test_the_write_covers_every_led_the_device_reports():
    """The regression: 82 written, 136 present."""
    profile = {i: (120, 100) for i in range(97)}
    device = {i: (0, 100) for i in range(136)}
    payload = F._led_payload(0, profile, device)
    assert len(payload) == 1 + 136 * 4 == 545, len(payload)
    assert len(leds(payload)) == 136


def test_leds_the_app_does_not_model_keep_what_the_device_has():
    """Not defaulted. 97-135 have no representation in the DB, and inventing a value there is
    what would wipe the module LEDs -- the opposite of the reported bug, equally wrong."""
    profile = {i: (120, 100) for i in range(97)}
    device = {i: (266, 100) for i in range(136)}          # board holds purple everywhere
    got = leds(F._led_payload(0, profile, device))
    assert all(got[i] == (120, 100) for i in range(97)), "profile colours not written"
    assert all(got[i] == (266, 100) for i in range(97, 136)), "unmodelled LEDs were overwritten"


def test_a_gap_inside_the_profile_range_is_unset_not_white():
    """(0, 0) is WHITE now the third byte is saturation, so an uncoloured key must carry the
    unset sentinel rather than lighting up bright white."""
    got = leds(F._led_payload(0, {0: (120, 100), 2: (240, 100)}, None))
    assert got[1] == UNSET, got[1]


def test_without_a_device_read_the_profile_still_bounds_the_write():
    """Recovery mode has no read to size against; it must still write what it knows."""
    payload = F._led_payload(0, {i: (120, 100) for i in range(97)}, None)
    assert len(leds(payload)) == 97


def test_an_empty_profile_and_no_device_writes_nothing():
    assert F._led_payload(0, {}, None) == bytes([0])


def test_the_binding_range_no_longer_limits_colour():
    """The exact guard that caused this: FULL_LAYER_POSITIONS stops at 0x51, and colours must
    not. If this ever fails, someone has reintroduced the conflation."""
    assert max(F.FULL_LAYER_POSITIONS) == 0x51
    profile = {i: (120, 100) for i in range(97)}          # includes 82..96, past the guard
    got = leds(F._led_payload(0, profile, None))
    assert all(got[i] == (120, 100) for i in range(82, 97)), "82-96 dropped again"


def test_the_payload_matches_nayaflows_own_write_size():
    """NayaFlow chunks its LED write 242/242/63. Net of the per-continuation index byte that is
    1 + 136*4; ours must be the same shape or we are writing a different map than the vendor."""
    payload = F._led_payload(0, {i: (0, 100) for i in range(97)},
                             {i: (0, 100) for i in range(136)})
    assert len(payload) == 545
    # 242 + 242 + 63 = 547, and the payload is 545: the two CONTINUATION frames each re-prefix
    # the layer index byte, so the wire total is two bytes larger than the payload.
    assert 242 + 242 + 63 == len(payload) + 2
