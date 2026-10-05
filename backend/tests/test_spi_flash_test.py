"""The SPIFLASH_TEST decode.

Until 2026-09-10 there was no captured device response to check against, so these tests pinned
the STRUCTURE that NayaCore's own format string forces (one status + five return codes per
partition, 2 + N x 6 bytes total, signed return codes, the 0-4 status enum) and that everything
else is refused or reported raw. Both halves of a healthy board have now answered
(device/out/spi-flash-selftest-20260910.json, test_spi_flash_live_capture.py), which confirmed
the lengths, the arithmetic and the status byte, and left one thing open: the return-code order
inside a partition, which an all-zero board cannot distinguish. `validated` is True and the
`validation` field says exactly that.

No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import spi_flash_test as S    # noqa: E402


def build(count, partitions, header=b"\x00\x00"):
    """A synthetic response. `partitions` is [(status, [5 return codes]), ...]."""
    out = bytearray(header)
    for status, codes in partitions:
        out.append(status)
        out += bytes((c & 0xFF) for c in codes)
    assert len(out) == 2 + count * 6
    return bytes(out)


HEALTHY_5 = build(5, [(3, [0] * 5)] * 5)
HEALTHY_3 = build(3, [(3, [0] * 5)] * 3)


def test_the_two_known_lengths_match_the_partition_arithmetic():
    assert S.LAYOUTS == {32: 5, 20: 3}
    for length, count in S.LAYOUTS.items():
        assert length == 2 + count * 6, (length, count)


def test_a_healthy_left_side_response_decodes_to_all_clear():
    d = S.decode(HEALTHY_5)
    assert d["partitionCount"] == 5 and len(d["partitions"]) == 5
    assert d["errored"] is False and d["erroredPartitions"] == []
    assert all(p["mounted"] for p in d["partitions"])
    assert S.summary(d)["state"] == "ok"


def test_the_right_side_layout_is_three_partitions():
    d = S.decode(HEALTHY_3)
    assert d["partitionCount"] == 3 and len(d["partitions"]) == 3
    assert S.summary(d)["state"] == "ok"


def test_return_codes_are_signed():
    """The whole point of reading them as int8: LFS_ERR_CORRUPT is -84, which as an unsigned byte
    would be 172 and would not match any known code."""
    d = S.decode(build(5, [(3, [0, -84, 0, 0, 0])] + [(3, [0] * 5)] * 4))
    mount = d["partitions"][0]["returnCodes"]["mount"]
    assert mount["value"] == -84
    assert mount["name"] == "LFS_ERR_CORRUPT"
    assert mount["ok"] is False


def test_every_named_return_code_round_trips():
    for value, name in S.RC_NAMES.items():
        d = S.decode(build(3, [(3, [value] + [0] * 4)] + [(3, [0] * 5)] * 2))
        assert d["partitions"][0]["returnCodes"]["open"]["name"] == name, value


def test_an_unnamed_return_code_is_reported_not_swallowed():
    d = S.decode(build(3, [(3, [-7] + [0] * 4)] + [(3, [0] * 5)] * 2))
    rc = d["partitions"][0]["returnCodes"]["open"]
    assert rc["value"] == -7 and "-7" in rc["name"] and rc["ok"] is False


def test_the_five_operations_are_kept_distinct():
    """Which operation failed is the diagnosis. Collapsing them to a boolean loses it."""
    d = S.decode(build(3, [(3, [0, 0, 0, -22, 0])] + [(3, [0] * 5)] * 2))
    p = d["partitions"][0]
    assert p["failingOperations"] == ["fileRead"]
    assert p["returnCodes"]["fileWrite"]["ok"] is True
    assert "fileRead" in S.summary(d)["detail"]


def test_the_status_enum_covers_zero_to_four():
    for value, name in S.STATUS_NAMES.items():
        d = S.decode(build(3, [(value, [0] * 5)] + [(3, [0] * 5)] * 2))
        assert d["partitions"][0]["statusName"] == name


def test_an_unknown_status_is_not_rounded_to_a_known_one():
    d = S.decode(build(3, [(9, [0] * 5)] + [(3, [0] * 5)] * 2))
    assert "Unknown" in d["partitions"][0]["statusName"]


def test_not_detected_with_clean_codes_is_not_called_an_error():
    """A different problem needing different advice: the partition is absent, not corrupt."""
    d = S.decode(build(3, [(0, [0] * 5)] + [(3, [0] * 5)] * 2))
    assert d["errored"] is False
    s = S.summary(d)
    assert s["state"] == "not-mounted" and "Not Detected" in s["detail"]


def test_errors_outrank_unmounted_in_the_summary():
    d = S.decode(build(3, [(0, [0] * 5), (3, [-84] * 5), (3, [0] * 5)]))
    assert S.summary(d)["state"] == "errors"


def test_an_unrecognised_length_is_refused_rather_than_partly_parsed():
    """NayaCore's own behaviour -- the expected length comes from the device type, so a length we
    do not know means we do not know the device, not that we should parse the first N bytes."""
    d = S.decode(b"\x00" * 26)
    assert d["layout"] is None and "partitions" not in d
    assert d["raw"] == "00" * 26
    assert "unrecognized" in d["note"]


def test_no_response_and_garbage_both_report_rather_than_raise():
    for bad in ("", None, b""):
        assert S.decode(bad)["layout"] is None
    assert S.decode("nothex")["layout"] is None
    assert S.summary(S.decode(""))["state"] == "unknown"


def test_the_undecoded_header_stays_raw_and_the_bytes_are_kept():
    d = S.decode(build(5, [(3, [0] * 5)] * 5, header=b"\x03\x05"))
    assert d["headerUnknown"] == "0305"
    assert d["raw"] == build(5, [(3, [0] * 5)] * 5, header=b"\x03\x05").hex()


def test_this_decode_still_declares_itself_unvalidated():
    """The honest flag. Flip it only when a real device response has been compared against this,
    and add that capture as a fixture in the same change."""
    assert S.decode(HEALTHY_5)["validated"] is True
    assert "return-code order" in S.decode(HEALTHY_5)["validation"], "the remaining gap must be named"


def test_partitions_are_reported_by_index_and_not_given_invented_names():
    """Six candidate names exist in the binary for a five-partition response and there is no
    evidence of which are used or in what order, so naming them would be a guess."""
    d = S.decode(HEALTHY_5)
    assert [p["index"] for p in d["partitions"]] == [0, 1, 2, 3, 4]
    assert not any("name" in p for p in d["partitions"])
