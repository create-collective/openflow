"""The interlocks that stand between a firmware image and a keyboard.

`firmware_upload.upload()` has never been run against hardware and nothing in this repository
calls it. What CAN be tested without hardware is every refusal -- and the refusals are the
feature. A wrong-generation or wrong-side image is the one mistake that turns a repair into a
brick, so each guard is asserted individually rather than through one happy path.

The device state fixtures below use the real hashes this keyboard reported on 2026-09-08:
slot 0 is kb_fwl.bin (left, generation A, 3.41.0) and slot 1 held an image we do not have.
No hardware.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import firmware_upload as fw    # noqa: E402

RUNNING_HASH = "479e89ba6c92ead9c46d1228d5033437caf63d72db89364081b9b0a321b31283"

CATALOG = [
    {"file": "kb_fwl.bin", "side": "left", "generation": "A", "createFirmware": "3.41.0",
     "plaintextSha256": RUNNING_HASH, "flashable": True, "withheldBecause": []},
    {"file": "kb_fwr.bin", "side": "right", "generation": "A", "createFirmware": "3.41.0",
     "plaintextSha256": "2abb2695", "flashable": True, "withheldBecause": []},
    {"file": "kb_fwl_64.bin", "side": "left", "generation": "B", "createFirmware": "3.41.0",
     "plaintextSha256": "07dd2523", "flashable": True, "withheldBecause": []},
    {"file": "kb_fwl_old.bin", "side": "left", "generation": "A", "createFirmware": "3.20.0",
     "plaintextSha256": "aaaa", "flashable": True, "withheldBecause": []},
    {"file": "win-NayaCore.exe-img0-sz304448.bin", "side": "left", "generation": None,
     "createFirmware": None, "plaintextSha256": "1b259d25", "flashable": False,
     "withheldBecause": ["flash generation unknown", "no declared firmware version"]},
]


def state_ok(side="left", generation="A", fw_version="3.41.0", identified=True):
    return {"state": "ok", "port": "COM4", "images": [
        {"slot": 0, "active": True, "hash": RUNNING_HASH, "identified": identified,
         "file": "kb_fwl.bin", "side": side, "generation": generation,
         "createFirmware": fw_version},
        {"slot": 1, "active": False, "hash": "036059b2", "identified": False},
    ]}


@pytest.fixture()
def images(tmp_path):
    """Stand-in image files. Contents are irrelevant: every guard fires before a byte is read."""
    for e in CATALOG:
        (tmp_path / e["file"]).write_bytes(b"\x00" * 4096)
    return tmp_path


def test_a_matching_image_produces_a_plan(images):
    p = fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok())
    assert p.slot == 1 and p.total_bytes == 4096
    assert p.arm_token == RUNNING_HASH, "the arm token must be the device's own reported hash"
    assert "kb_fwl.bin" in p.describe()


def test_the_wrong_side_is_refused(images):
    with pytest.raises(fw.UploadRefused, match="different binaries"):
        fw.plan(images / "kb_fwr.bin", CATALOG, state=state_ok())


def test_the_wrong_generation_is_refused(images):
    """The failure that matters most: same side, same version, incompatible flash."""
    with pytest.raises(fw.UploadRefused, match="generation"):
        fw.plan(images / "kb_fwl_64.bin", CATALOG, state=state_ok())


def test_a_withheld_image_is_refused(images):
    with pytest.raises(fw.UploadRefused, match="withheld"):
        fw.plan(images / "win-NayaCore.exe-img0-sz304448.bin", CATALOG, state=state_ok())


def test_an_uncatalogued_file_is_refused(images):
    (images / "mystery.bin").write_bytes(b"\x00" * 16)
    with pytest.raises(fw.UploadRefused, match="not in the firmware catalogue"):
        fw.plan(images / "mystery.bin", CATALOG, state=state_ok())


def test_a_device_that_will_not_identify_itself_is_refused(images):
    with pytest.raises(fw.UploadRefused, match="not one we hold"):
        fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok(identified=False))


def test_a_device_that_did_not_answer_is_refused(images):
    with pytest.raises(fw.UploadRefused, match="did not report its image state"):
        fw.plan(images / "kb_fwl.bin", CATALOG,
                state={"state": "error", "detail": "neither port answered"})


def test_downgrade_is_refused_by_default_but_is_not_forbidden(images):
    """Going back a version is a real repair -- two halves that no longer talk are brought to a
    common one -- so it must be possible, and must be deliberate."""
    with pytest.raises(fw.UploadRefused, match="older"):
        fw.plan(images / "kb_fwl_old.bin", CATALOG, state=state_ok())
    p = fw.plan(images / "kb_fwl_old.bin", CATALOG, state=state_ok(), allow_older=True)
    assert p.target["createFirmware"] == "3.20.0"


def test_same_version_reflash_is_allowed(images):
    """Re-writing the version already installed is the ordinary repair for a corrupt image."""
    assert fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok()).total_bytes == 4096


def test_upload_refuses_without_the_device_specific_arm_token(images, monkeypatch):
    """A boolean flag can be left switched on. A token tied to the device in front of you
    cannot be reused on the next one by accident."""
    def boom(*a, **k):
        raise AssertionError("a frame was sent despite the arm check failing")
    monkeypatch.setattr(fw.rec, "_talk", boom)
    for bad in ("", "true", "yes", "0" * 64):
        with pytest.raises(fw.UploadRefused, match="not armed"):
            fw.upload(images / "kb_fwl.bin", CATALOG, arm=bad, state=state_ok())


def test_nothing_in_the_app_calls_upload():
    """The guard against this being wired up before a donor unit exists."""
    root = _BACKEND / "openflow_backend"
    callers = []
    for f in root.rglob("*.py"):
        if f.name == "firmware_upload.py" or "_vendor" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "firmware_upload" in text:
            callers.append(str(f.relative_to(root)))
    assert not callers, f"firmware_upload is referenced by {callers}; it must stay uncalled"


# --- request shape --------------------------------------------------------------------------- #

def _decode_request(frame: bytes) -> dict:
    """Frame -> the CBOR body, so assertions are about what the bootloader receives rather than
    about base64 text."""
    import base64
    from openflow_backend.device import recovery as rec
    body = base64.b64decode(frame[2:-1])[2:-2]      # strip markers, length prefix, CRC
    value, _ = rec._cbor_decode(body[8:])           # skip the 8-byte SMP header
    return value

def test_first_chunk_carries_length_and_hash_and_later_ones_do_not():
    data = b"\x01\x02\x03"
    sha = hashlib.sha256(b"whole image").digest()
    first = _decode_request(fw.build_chunk_request(1, 0, data, total=999, sha=sha))
    later = _decode_request(fw.build_chunk_request(1, 3, data, seq=1))
    assert first == {"image": 1, "off": 0, "data": data, "len": 999, "sha": sha}, first
    assert later == {"image": 1, "off": 3, "data": data}, later


def test_a_first_chunk_without_the_total_is_a_programming_error():
    with pytest.raises(ValueError, match="first chunk"):
        fw.build_chunk_request(1, 0, b"\x00")


def test_cbor_encoder_round_trips_through_our_own_decoder():
    from openflow_backend.device import recovery as rec
    for value in (0, 23, 24, 255, 256, 70000, True, False, b"", b"\xff" * 40, "off",
                  {"image": 1, "off": 4096, "data": b"\x01\x02"}):
        got, _ = rec._cbor_decode(fw._cbor_encode(value))
        assert got == value, f"{value!r} -> {got!r}"


def test_chunk_count_matches_the_image_size(images):
    p = fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok(), chunk=100)
    assert p.chunks == 41, p.chunks          # 4096 / 100 rounded up
    assert p.image_sha256 == hashlib.sha256(b"\x00" * 4096).hexdigest()
