"""SMP framing, CBOR decoding, and matching a running image against the catalogue.

This is the code path a future firmware repair would be gated on, so it is tested before it is
ever pointed at hardware. Everything here is offline: frames are built and parsed in memory and
no serial port is opened.

The reference frame below is built by our own encoder and parsed by our own decoder, which
proves they agree but not that they match MCUboot. What pins the format against the real thing
is the CRC algorithm (CRC16-XMODEM over the body) and the header layout, both asserted
explicitly against hand-computed values rather than against our own output.

Context: the Create's recovery interface supports only `os echo` and `image state` -- a live
probe on 2026-09-01 found fs, enumeration, os params and bootloader-info all ENOTSUP. There is
deliberately no upload path in recovery.py.
No hardware.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import recovery as rec    # noqa: E402


# --- CBOR ------------------------------------------------------------------------------------ #

def test_cbor_primitives():
    for raw, want in [
        (b"\x00", 0), (b"\x0a", 10), (b"\x18\x2a", 42),
        (b"\x19\x01\x00", 256), (b"\x1a\x00\x01\x00\x00", 65536),
        (b"\x20", -1), (b"\xf4", False), (b"\xf5", True),
        (b"\x63abc", "abc"), (b"\x43\x01\x02\x03", b"\x01\x02\x03"),
    ]:
        got, end = rec._cbor_decode(raw)
        assert got == want, f"{raw!r} -> {got!r}, wanted {want!r}"
        assert end == len(raw), f"{raw!r} consumed {end} of {len(raw)}"


def test_cbor_nested_map_and_array():
    # {"images": [{"slot": 0, "active": true}]}
    raw = (b"\xa1" + b"\x66images" + b"\x81"
           + b"\xa2" + b"\x64slot" + b"\x00" + b"\x66active" + b"\xf5")
    got, _ = rec._cbor_decode(raw)
    assert got == {"images": [{"slot": 0, "active": True}]}, got


def test_cbor_indefinite_length_containers():
    """Zephyr encodes indefinite-length maps in some builds; a decoder that cannot read one
    would fail against real hardware and never against a fixture we wrote ourselves."""
    raw = b"\xbf" + b"\x64slot" + b"\x01" + b"\xff"
    got, end = rec._cbor_decode(raw)
    assert got == {"slot": 1} and end == len(raw), (got, end)


def test_cbor_rejects_rather_than_guesses():
    for bad in (b"", b"\x1c", b"\xe0"):
        try:
            rec._cbor_decode(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have raised")


# --- CRC and framing ------------------------------------------------------------------------- #

def test_crc16_xmodem_against_known_vectors():
    """The published CRC16/XMODEM check value. If this drifts, every frame we send is rejected
    by the bootloader and the failure would look like a dead device."""
    assert rec._crc16_xmodem(b"123456789") == 0x31C3
    assert rec._crc16_xmodem(b"") == 0x0000


def test_request_header_layout():
    frame = rec.encode_request(rec.SMP_OP_READ, rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_STATE)
    assert frame.startswith(b"\x06\x09") and frame.endswith(b"\n")
    import base64
    body = base64.b64decode(frame[2:-1])
    length = struct.unpack(">H", body[:2])[0]
    op, flags, plen, group, seq, cmd = struct.unpack(">BBHHBB", body[2:10])
    # The prefix covers body + CRC, which is what mcumgr's serial transport sends (htons(len+2)).
    # This assertion previously encoded the opposite and passed happily while the bootloader
    # ignored every frame we sent.
    assert length == len(body) - 2, "the length prefix must cover the body AND the CRC"
    # `op` here is the whole first byte: version in bits 3-4, op in bits 0-2.
    assert (op, flags, group, seq, cmd) == (0x08, 0, 1, 0, 0), (op, flags, group, seq, cmd)
    assert plen == 1, "an empty CBOR map is one byte"


def test_response_round_trip():
    payload = (b"\xa1" + b"\x66images" + b"\x81" + b"\xa2"
               + b"\x64slot" + b"\x00" + b"\x64hash" + b"\x43\xaa\xbb\xcc")
    body = rec._smp_header(rec.SMP_OP_READ_RSP, rec.SMP_GROUP_IMAGE,
                           rec.SMP_ID_IMAGE_STATE, len(payload)) + payload
    import base64
    framed = struct.pack(">H", len(body) + 2) + body + struct.pack(">H", rec._crc16_xmodem(body))
    line = b"\x06\x09" + base64.b64encode(framed) + b"\n"
    got = rec.decode_response(line)
    assert got["images"][0]["hash"] == b"\xaa\xbb\xcc", got


def test_a_corrupted_frame_is_refused_not_interpreted():
    """A mangled response must raise, not decode to something plausible -- this feeds a decision
    about which firmware a device is running."""
    payload = b"\xa0"
    body = rec._smp_header(1, 1, 0, len(payload)) + payload
    import base64
    bad = struct.pack(">H", len(body) + 2) + body + struct.pack(">H", 0x0000)   # wrong CRC
    try:
        rec.decode_response(b"\x06\x09" + base64.b64encode(bad) + b"\n")
    except ValueError as e:
        assert "CRC" in str(e)
        return
    raise AssertionError("a bad CRC decoded successfully")


def test_no_frame_at_all_raises():
    try:
        rec.decode_response(b"some log line\r\nanother\r\n")
    except ValueError:
        return
    raise AssertionError("log output should not parse as a frame")


# --- identifying a running image ------------------------------------------------------------- #

CATALOG = [
    {"file": "kb_fwl.bin", "plaintextSha256": "479e89ba", "side": "left",
     "generation": "A", "createFirmware": "3.41.0", "source": "NayaFlow 1.25.1", "flashable": True,
     "bundle": "NayaFlow 1.25.1", "versionLabel": "3.41.0", "releaseOrder": 24},
    {"file": "old.bin", "plaintextSha256": "deadbeef", "side": "left",
     "generation": None, "createFirmware": None, "source": "NayaFlow 1.17.3", "flashable": False},
]


def test_a_known_image_is_named():
    got = rec.identify("479e89ba", CATALOG)
    assert got["identified"] and got["side"] == "left" and got["generation"] == "A", got


def test_a_known_image_says_which_release_shipped_it():
    """So Information can say 'NayaFlow 1.25.1 shipped this', and the flasher can order two
    images whose version numbers no release ever declared."""
    got = rec.identify("479e89ba", CATALOG)
    assert (got["bundle"], got["versionLabel"], got["releaseOrder"]) == ("NayaFlow 1.25.1", "3.41.0", 24)
    old = rec.identify("deadbeef", CATALOG)
    assert old["identified"] and old["bundle"] is None and old["releaseOrder"] is None


def test_an_unknown_image_is_not_guessed():
    """The failure that matters: never infer a side or generation we cannot prove, because a
    wrong generation is exactly what must not be written."""
    got = rec.identify("ffffffff", CATALOG)
    assert got["identified"] is False and "cannot say" in got["why"], got


def test_a_known_but_withheld_image_reports_its_flashability():
    got = rec.identify("deadbeef", CATALOG)
    assert got["identified"] is True and got["flashable"] is False, got


def test_no_hash_is_not_treated_as_a_match():
    assert rec.identify(None, CATALOG)["identified"] is False
    assert rec.identify("", CATALOG)["identified"] is False


def test_empty_catalog_matches_nothing():
    assert rec.identify("479e89ba", [])["identified"] is False
    assert rec.identify("479e89ba", None)["identified"] is False


# --- pinned against a reference implementation ------------------------------------------------ #
# Everything above validates our encoder against our own decoder, which proves they agree and
# nothing more. This compares the bytes to the `smp` library, and it is the assertion that would
# actually have caught the bug that cost six reboots: the first header byte carries the SMP
# protocol VERSION in bits 3-4, not just the op, and we were sending version 0. The bootloader
# did not reject that -- it ignored it, which looks exactly like a dead port.

def test_our_request_matches_the_reference_client_byte_for_byte():
    try:
        from smp import image_management as im
    except ImportError:                       # pragma: no cover - optional dev dependency
        import pytest
        pytest.skip("smp not installed; this pins framing against the reference client")
    ours = rec._smp_header(rec.SMP_OP_READ, rec.SMP_GROUP_IMAGE,
                           rec.SMP_ID_IMAGE_STATE, 1) + b"\xa0"
    assert ours == bytes(im.ImageStatesReadRequest()), (
        f"our framing drifted from the reference: {ours.hex()}")


def test_the_version_bits_are_actually_set():
    """Stated separately so the reason survives even if `smp` is not installed."""
    hdr = rec._smp_header(rec.SMP_OP_READ, rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_STATE, 1)
    assert hdr[0] == 0x08, f"first byte {hdr[0]:#04x}: version bits missing, op-only header"
    assert hdr[0] & 0x07 == rec.SMP_OP_READ, "the op must survive in the low three bits"
