"""The layer-list animation byte follows ZMK's effect order; the LED effect key does not.

Two NayaFlow flashes, each with the animation set per layer in NayaFlow's own UI, read back
as raw layer lists (tools/backup_device.py, `layer_list_raw`):

  2026-09-08 probe profile   Typing breathe, Keypad SWIRL, System SPECTRUM   ->  1, 3, 2
  2026-09-09 16:57           Typing solid,   Keypad breathe, System SWIRL    ->  0, 1, 3

So byte 2 is solid 0 / breathe 1 / spectrum 2 / swirl 3 -- ZMK's underglow order -- while the
LED effect KEY's argument (record 0x09, subcommand 0x0d) is NayaCore's own: swirl 2, spectrum 3,
pinned by pairing the stock System layer's records with NayaFlow's database and by NayaCore's
table. Until 2026-09-09 one table served both, swapping swirl and spectrum for the layer byte:
a swirl layer read as spectrum, and a flash wrote it back the other way. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

# device/out/verify-probe-after-nayaflow.json (13:55) and device/out/after-nayaflow-2.json (17:0x).
PROBE = bytes.fromhex("03000001100cb76a711d4243c88b4eab1c521695c901010310c32c7d56a47244bbac09f8b526efa8c1"
                      "020202105cea2e1036bc4dd590dcbfd61e13a1f9")
LATEST = bytes.fromhex("03000000100cb76a711d4243c88b4eab1c521695c901010110c32c7d56a47244bbac09f8b526efa8c1"
                       "020203105cea2e1036bc4dd590dcbfd61e13a1f9")


def _names(raw: bytes) -> dict[int, str]:
    _idx, _uuids, anims = kr.parse_layer_list(raw)
    return {i: kr.LAYER_ANIMATIONS[a] for i, a in anims.items()}


def test_the_probe_profile_reads_as_nayaflow_set_it():
    assert _names(PROBE) == {0: "breathe", 1: "swirl", 2: "spectrum"}
    print("  1 / 3 / 2 -> breathe / swirl / spectrum")


def test_the_latest_flash_reads_as_the_user_set_it():
    assert _names(LATEST) == {0: "solid", 1: "breathe", 2: "swirl"}
    print("  0 / 1 / 3 -> solid / breathe / swirl")


def test_the_uuids_survive_both():
    for raw in (PROBE, LATEST):
        _idx, uuids, _a = kr.parse_layer_list(raw)
        assert uuids[0] == "0cb76a71-1d42-43c8-8b4e-ab1c521695c9"
        assert uuids[2] == "5cea2e10-36bc-4dd5-90dc-bfd61e13a1f9"


def test_a_swirl_layer_writes_byte_three_and_the_swirl_key_writes_argument_two():
    """The two enums differ, and must stay separate tables."""
    assert kr.LAYER_ANIMATION_IDS["swirl"] == 3 and kr.LAYER_ANIMATION_IDS["spectrum"] == 2
    entry = R.encode_layer_list_entries([(2, R.layer_uuid_bytes("5cea2e10-36bc-4dd5-90dc-bfd61e13a1f9"),
                                          kr.LAYER_ANIMATION_IDS["swirl"])])
    assert entry[3] == 3
    swirl_key = R.encode_rgb_system("LED_SWIRL")
    assert int.from_bytes(swirl_key[4:8], "little") == 2
    spec_key = R.encode_rgb_system("LED_SPEC")
    assert int.from_bytes(spec_key[4:8], "little") == 3
    print("  layer byte swirl=3 / spectrum=2; effect key swirl=2 / spectrum=3")


def test_round_trip_through_the_layer_list_encoder():
    _idx, uuids, anims = kr.parse_layer_list(LATEST)
    entries = [(i, R.layer_uuid_bytes(uuids[i]), anims[i]) for i in sorted(anims)]
    again = kr.parse_layer_list(R.encode_layer_list_entries(entries))[2]
    assert again == anims
    print("  parse -> encode -> parse keeps every animation byte")


if __name__ == "__main__":
    for fn in (test_the_probe_profile_reads_as_nayaflow_set_it, test_the_latest_flash_reads_as_the_user_set_it,
               test_the_uuids_survive_both, test_a_swirl_layer_writes_byte_three_and_the_swirl_key_writes_argument_two,
               test_round_trip_through_the_layer_list_encoder):
        print(fn.__name__)
        fn()
    print("\nOK")
