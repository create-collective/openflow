"""The first real SPIFLASH_TEST responses, both halves of a healthy Create on 3.41.0.

Captured 2026-09-10 over two separate USB cables (device/out/spi-flash-selftest-20260910.json).
Before this the decoder had only ever seen vectors its own author built. These bytes are what
the structure was checked against, and they are kept here so the check cannot drift.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import spi_flash_test as S  # noqa: E402

LEFT = "0100030000000000030000000000030000000000030000000000030000000000"
RIGHT = "0100000000000000030000000000030000000000"


def test_the_left_half_is_five_mounted_partitions():
    d = S.decode(LEFT)
    assert d["layout"] == "32-byte" and d["partitionCount"] == 5
    assert [p["statusName"] for p in d["partitions"]] == ["Mounted"] * 5
    assert not d["errored"] and d["headerUnknown"] == "0100"
    assert S.summary(d)["state"] == "ok"
    print("  left: 5 x Mounted, no errors, header 0100")


def test_the_right_half_is_three_partitions_with_the_first_absent():
    d = S.decode(RIGHT)
    assert d["layout"] == "20-byte" and d["partitionCount"] == 3
    assert [p["statusName"] for p in d["partitions"]] == ["Not Detected", "Mounted", "Mounted"]
    assert not d["errored"], "Not Detected with clean codes is a state, not an error"
    assert S.summary(d)["state"] == "not-mounted"
    print("  right: #0 Not Detected, #1-2 Mounted, no errors")


def test_the_status_byte_is_first_in_each_block():
    """The one ordering the capture CAN prove: 03 leads every mounted block and 00 the absent one,
    with the five codes after it. The order among the five codes is not provable from zeros."""
    for raw, count in ((LEFT, 5), (RIGHT, 3)):
        b = bytes.fromhex(raw)
        for i in range(count):
            blk = b[2 + i * 6: 8 + i * 6]
            assert blk[0] in (0, 3) and blk[1:] == bytes(5), blk.hex()
    print("  status leads each six-byte block; the five codes behind it are all zero")


def test_the_decoder_calls_itself_validated_and_names_the_gap():
    d = S.decode(LEFT)
    assert d["validated"] is True
    assert "return-code order" in d["validation"]
    print("  validated, with the return-code order named as the remaining gap")


if __name__ == "__main__":
    for fn in (test_the_left_half_is_five_mounted_partitions,
               test_the_right_half_is_three_partitions_with_the_first_absent,
               test_the_status_byte_is_first_in_each_block,
               test_the_decoder_calls_itself_validated_and_names_the_gap):
        print(fn.__name__)
        fn()
    print("\nOK")
