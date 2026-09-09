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


def test_the_module_blocks_are_written_from_their_own_colours():
    """LEDs 88-96 light the LEFT module and 112-126 the RIGHT, measured by painting each band a
    distinct colour and looking at the keyboard. The right block has NO key position behind it,
    which is why a flash used to leave the right module on whatever wrote it last.

    This replaces an earlier rule that wrote all of 97-135 from key position 88 -- that made both
    modules the same colour, tied them to an arbitrary key, and painted two bands that light
    nothing."""
    profile = {i: (120, 100) for i in range(97)}
    device = {i: (0, 100) for i in range(136)}
    got = leds(F._led_payload(0, profile, device,
                              {"left": "#ff0000", "right": "#0000ff"}))
    assert all(got[i] == (0, 100) for i in F.MODULE_LED_BLOCKS["left"]), "left block not written"
    assert all(got[i] == (240, 100) for i in F.MODULE_LED_BLOCKS["right"]), "right block not written"


def test_each_bay_gets_twenty_four_leds_and_they_are_symmetric():
    """A bay's block is 24 LEDs and the module lights as many as it HAS -- a Tune 9, a Track 15 --
    which is why 97-111 and 127-135 looked dead with a Tune left and a Track right. They are the
    unused tail of each block, not a separate structure.

    Keyed to the BAY, not the module: swapping the two kept each side's colour."""
    assert len(F.MODULE_LED_BLOCKS["left"]) == len(F.MODULE_LED_BLOCKS["right"]) == 24
    assert F.MODULE_LED_BLOCKS["left"].stop == F.MODULE_LED_BLOCKS["right"].start
    device = {i: (300, 100) for i in range(136)}
    got = leds(F._led_payload(0, {i: (120, 100) for i in range(97)}, device,
                              {"left": "#ff0000", "right": "#0000ff"}))
    # the whole block is painted, so it is right whatever module is docked in it
    assert all(got[i] == (0, 100) for i in range(88, 112))
    assert all(got[i] == (240, 100) for i in range(112, 136))


def test_a_module_colour_overrides_the_key_colour_underneath_it():
    """The left block sits INSIDE the key range, so both could claim those LEDs. The explicit
    module colour must win, or setting it would appear to do nothing."""
    profile = {i: (120, 100) for i in range(97)}
    got = leds(F._led_payload(0, profile, None, {"left": "#ff0000"}))
    assert all(got[i] == (0, 100) for i in F.MODULE_LED_BLOCKS["left"])
    assert got[50] == (120, 100)


def test_no_module_colour_keeps_whatever_the_device_has():
    """Unset must not mean "paint it something". A user who has never touched the setting keeps
    the module they see."""
    device = {i: (266, 100) for i in range(136)}
    got = leds(F._led_payload(0, {i: (120, 100) for i in range(97)}, device, None))
    assert all(got[i] == (266, 100) for i in F.MODULE_LED_BLOCKS["right"])


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
    not. If this ever fails, someone has reintroduced the conflation.

    _led_payload writes what it is given, so it is checked with colours up to 96 here; the DB
    path (desired_from_db) stops key colours at 87, because 88-96 are the left bay block --
    see tests/test_bay_block_rule.py."""
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
