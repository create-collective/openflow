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


def test_the_pid_and_the_running_image_must_agree_on_side_and_generation(images):
    """Two independent sources: the USB product id (NayaCore's table) and the catalogued hash of
    the running image. A half whose descriptor says generation B while it runs a generation-A
    image is a half nobody understands, and nothing is written to it."""
    agree = state_ok()
    agree.update({"pid": 0x006F, "pidSide": "left", "pidGeneration": "A"})
    assert fw.plan(images / "kb_fwl.bin", CATALOG, state=agree).upload_image_id == 2
    gen_b_pid = state_ok()
    gen_b_pid.update({"pid": 0x106F, "pidSide": "left", "pidGeneration": "B"})
    with pytest.raises(fw.UploadRefused, match="Two sources disagree"):
        fw.plan(images / "kb_fwl.bin", CATALOG, state=gen_b_pid)
    right_pid = state_ok()
    right_pid.update({"pid": 0x00D3, "pidSide": "right", "pidGeneration": "A"})
    with pytest.raises(fw.UploadRefused, match="Two sources disagree"):
        fw.plan(images / "kb_fwl.bin", CATALOG, state=right_pid)


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
    _patch_transport(monkeypatch, boom)
    for bad in ("", "true", "yes", "0" * 64):
        with pytest.raises(fw.UploadRefused, match="not armed"):
            fw.upload(images / "kb_fwl.bin", CATALOG, arm=bad, state=state_ok())


def test_upload_is_wired_only_through_the_gated_endpoint():
    """The flasher is now wired (owner ask 2026-09-14), but the safety property is unchanged: the
    upload path may be referenced ONLY by api/rest.py, and that reference must sit behind the hard
    FIRMWARE_FLASH_ENABLED gate, which ships False. So even with an arm token the endpoint refuses
    until a donor test flips the gate. If any other module starts importing firmware_upload, or the
    gate default drifts to True, this fails."""
    import re

    root = _BACKEND / "openflow_backend"

    def referrers(name):
        """The modules that IMPORT `name`.

        This used to be a search for the bare word, which counted comments and docstrings as
        wiring. It fired on prose: the progress stream and the run registry (SCRUM-102) both
        explain why they must not take the service lock the procedure holds, and naming the
        procedure while doing so is exactly how that explanation reads. An import is what makes
        a module reachable -- nothing can call flash_procedure.run without one -- so that is what
        is checked, and the safety property is unchanged.
        """
        pat = re.compile(rf"^\s*(?:from\s+\S+\s+import\s+.*\b{name}\b|import\s+.*\b{name}\b)",
                         re.M)
        out = []
        for f in root.rglob("*.py"):
            if f.name == f"{name}.py" or "_vendor" in f.parts:
                continue
            if pat.search(f.read_text(encoding="utf-8", errors="ignore")):
                out.append(f.relative_to(root).as_posix())
        return sorted(out)

    # device/flash_procedure.py is the ONLY module besides the endpoint allowed to reach the
    # uploader: it is the logged, verified procedure (SCRUM-108) and it drives flash() directly.
    # The gate is preserved by the second assertion -- the procedure itself is reachable only
    # through api/rest.py, so there is still exactly one gated way in.
    assert referrers("firmware_upload") == ["api/rest.py", "device/flash_procedure.py"], (
        "firmware_upload must be referenced only by api/rest.py and device/flash_procedure.py; "
        f"found {referrers('firmware_upload')}")
    assert referrers("flash_procedure") == ["api/rest.py"], (
        "flash_procedure must be reachable only through the gated endpoint; "
        f"found {referrers('flash_procedure')}")
    rest = (root / "api" / "rest.py").read_text(encoding="utf-8")
    # The gate is driven by the environment, so it cannot be committed on by accident the way an
    # edited `= True` can. What matters here is that it is never UNCONDITIONALLY open; that it is
    # off by default, and open only for the exact value "1", is checked by behaviour in
    # tests/test_firmware_gate.py rather than by reading the source.
    assert 'FIRMWARE_FLASH_ENABLED = os.environ.get("OPENFLOW_ENABLE_FIRMWARE_FLASH") == "1"' in rest, (
        "the flasher gate must be the environment read -- never a hardcoded value")
    assert "FIRMWARE_FLASH_ENABLED = True" not in rest
    # the gate must actually guard the endpoint, not merely be defined
    assert "if not FIRMWARE_FLASH_ENABLED:" in rest


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


# --- the swap: mark pending + reset (what upload() alone never does) ------------------------- #
# Ids are stock mcumgr: image group 1 / state 0 / upload 1; os group 0 / reset 5. NayaCore speaks
# stock SMP in every release (nayaHistory/FLASHING-PROCEDURE.md), so these are not guesses.

def _decode_header(frame: bytes) -> dict:
    import base64
    import struct
    body = base64.b64decode(frame[2:-1])[2:-2]
    return {"op": body[0] & 0x07, "group": struct.unpack(">H", body[4:6])[0], "id": body[7]}


def test_mark_pending_is_an_image_state_write_carrying_hash_and_confirm_flag():
    sha = hashlib.sha256(b"x").digest()
    f = fw.build_set_pending_request(sha)
    assert _decode_header(f) == {"op": 2, "group": 1, "id": 0}
    assert _decode_request(f) == {"hash": sha, "confirm": False}          # MCUboot TEST swap
    assert _decode_request(fw.build_set_pending_request(sha, confirm=True)) == {"hash": sha, "confirm": True}
    # No hash-less form: in serial recovery {"confirm": true} alone is not "confirm the running
    # image", it schedules a permanent swap of the secondary (bs_set -> boot_set_pending_multi).
    with pytest.raises(ValueError, match="needs the hash"):
        fw.build_set_pending_request(None, confirm=True)
    with pytest.raises(ValueError, match="needs the hash"):
        fw.build_set_pending_request(None)
    with pytest.raises(ValueError, match="32 bytes"):
        fw.build_set_pending_request(b"short")


def test_reset_is_an_os_reset_write_with_an_empty_map():
    f = fw.build_reset_request()
    assert _decode_header(f) == {"op": 2, "group": 0, "id": 5}
    assert _decode_request(f) == {}



def _patch_transport(monkeypatch, talk):
    """Stub BOTH transport seams from one fake.

    rec._talk is the per-request path used by probes; rec.session is the one-open-port path a
    bulk upload uses. A test that stubs only the first would let _send_chunks reach for a real
    serial port.
    """
    import contextlib as _contextlib
    monkeypatch.setattr(fw.rec, "_talk", talk)

    @_contextlib.contextmanager
    def _fake_session(port, timeout=5.0):
        yield lambda frame, _t=timeout: talk(port, frame, timeout=_t)

    monkeypatch.setattr(fw.rec, "session", _fake_session)


def _fake_bootloader(landed_hash_hex: str, log: list):
    """Answers like MCUboot: a chunk -> the next offset; a state read -> slot 1 holds
    `landed_hash_hex`; anything else -> rc 0. Records (header, body) of every frame."""
    def talk(port, frame, timeout=2.0):
        h, body = _decode_header(frame), _decode_request(frame)
        log.append((h, body))
        if h == {"op": 2, "group": 1, "id": 1}:
            return {"rc": 0, "off": body["off"] + len(body["data"])}
        if h == {"op": 0, "group": 1, "id": 0}:
            return {"images": [{"slot": 0, "hash": bytes.fromhex(RUNNING_HASH)},
                               {"slot": 1, "hash": bytes.fromhex(landed_hash_hex)}]}
        return {"rc": 0}
    return talk


def _kinds(log):
    return [(h["group"], h["id"], h["op"]) for h, _ in log]


def test_flash_is_slot_map_then_upload_then_slot_check_then_mark_then_reset(images, monkeypatch):
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    r = fw.flash(images / "kb_fwl.bin", CATALOG, arm=RUNNING_HASH, state=state_ok(), chunk=1024)
    assert _kinds(log)[0] == (1, 6, 0)                              # slot map read first
    assert _kinds(log)[1:5] == [(1, 1, 2)] * 4                      # 4096 B / 1024 = 4 chunks
    assert _kinds(log)[5:] == [(1, 0, 0), (1, 0, 2), (0, 5, 2)]     # read, mark, reset
    assert log[6][1] == {"hash": bytes.fromhex(RUNNING_HASH), "confirm": False}
    assert r["swap"] == "test" and r["hash"] == RUNNING_HASH and r["reset"] is True


def test_flash_confirm_true_marks_permanent(images, monkeypatch):
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    r = fw.flash(images / "kb_fwl.bin", CATALOG, arm=RUNNING_HASH, state=state_ok(),
                 chunk=1024, confirm=True)
    assert log[6][1]["confirm"] is True and r["swap"] == "permanent"


def test_flash_never_marks_a_slot_whose_hash_is_not_the_target(images, monkeypatch):
    """The upload landed, but the slot does not read back as the image we meant. Stop dead:
    no mark, no reset, primary untouched."""
    log = []
    _patch_transport(monkeypatch, _fake_bootloader("ab" * 32, log))
    with pytest.raises(fw.UploadRefused, match="Nothing is scheduled"):
        fw.flash(images / "kb_fwl.bin", CATALOG, arm=RUNNING_HASH, state=state_ok(), chunk=1024)
    assert _kinds(log)[-1] == (1, 0, 0), "must stop right after the slot read"
    assert (1, 0, 2) not in _kinds(log) and (0, 5, 2) not in _kinds(log)


def test_flash_never_marks_an_image_with_no_catalogued_plaintext_hash(images, monkeypatch):
    """kb_fwl_old.bin carries a stub hash. Without a full one the slot cannot be verified, so
    nothing after the upload is sent -- not even the state read."""
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    with pytest.raises(fw.UploadRefused, match="no catalogued plaintext hash"):
        fw.flash(images / "kb_fwl_old.bin", CATALOG, arm=RUNNING_HASH, state=state_ok(),
                 chunk=1024, allow_older=True)
    assert set(_kinds(log)) == {(1, 6, 0), (1, 1, 2)}, "only the slot map read and upload chunks may have been sent"


def test_flash_refuses_without_the_arm_token_before_sending_anything(images, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a frame was sent despite the arm check failing")
    _patch_transport(monkeypatch, boom)
    with pytest.raises(fw.UploadRefused, match="not armed"):
        fw.flash(images / "kb_fwl.bin", CATALOG, arm="", state=state_ok())


# --- a file is matched to its catalogue entry by its bytes, not its name ---------------------- #
# Every NayaFlow release since 0.1.0 names its left image kb_fwl.bin, so the catalogue built from
# all 25 releases (tools/build_firmware_catalog.py) holds a dozen entries with that name. Only the
# hash of the file can say which one a given kb_fwl.bin is, and a catalogued name with unknown
# bytes must be refused, not matched to the first entry that happens to carry the name.

def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


NEW_BYTES, OLD_BYTES = b"\x02" * 2048, b"\x01" * 2048
HASHED_CATALOG = [
    {"file": "kb_fwl.bin", "side": "left", "generation": "A", "createFirmware": "3.41.0",
     "plaintextSha256": RUNNING_HASH, "blobSha256": _sha(NEW_BYTES), "releaseOrder": 24,
     "versionLabel": "3.41.0", "bundle": "NayaFlow 1.25.1", "flashable": True, "withheldBecause": []},
    {"file": "kb_fwl.bin", "side": "left", "generation": "A", "createFirmware": None,
     "plaintextSha256": "83100f7b" * 8, "blobSha256": _sha(OLD_BYTES), "releaseOrder": 9,
     "versionLabel": "NayaFlow 1.11.0, 1.11.9", "bundle": "NayaFlow 1.11.9", "flashable": True,
     "withheldBecause": []},
]


def _running(**extra):
    st = state_ok()
    st["images"][0].update(extra)
    return st


def test_a_file_is_matched_by_its_hash_when_catalogue_names_collide(tmp_path):
    (tmp_path / "kb_fwl.bin").write_bytes(OLD_BYTES)
    p = fw.plan(tmp_path / "kb_fwl.bin", HASHED_CATALOG, state=_running(releaseOrder=24),
                allow_older=True)
    assert p.target["releaseOrder"] == 9 and p.target["versionLabel"] == "NayaFlow 1.11.0, 1.11.9"
    assert "NayaFlow 1.11.9" in p.describe()


def test_a_catalogued_name_with_unknown_bytes_is_refused(tmp_path):
    (tmp_path / "kb_fwl.bin").write_bytes(b"\x03" * 2048)
    with pytest.raises(fw.UploadRefused, match="match none"):
        fw.plan(tmp_path / "kb_fwl.bin", HASHED_CATALOG, state=state_ok())


def test_duplicate_names_without_hashes_are_ambiguous_not_first_wins(tmp_path):
    (tmp_path / "kb_fwl.bin").write_bytes(OLD_BYTES)
    nameless = [{k: v for k, v in e.items() if k != "blobSha256"} for e in HASHED_CATALOG]
    with pytest.raises(fw.UploadRefused, match="ambiguous"):
        fw.plan(tmp_path / "kb_fwl.bin", nameless, state=state_ok())


def test_release_order_guards_a_downgrade_when_no_version_number_was_declared(tmp_path):
    """Most images before 1.14.5 have no version number anywhere (no changelog heading, nothing
    in the app JS). The order of the releases that shipped them is the only guide, and it must
    still make the downgrade deliberate."""
    (tmp_path / "kb_fwl.bin").write_bytes(OLD_BYTES)
    with pytest.raises(fw.UploadRefused, match="release order is the only guide"):
        fw.plan(tmp_path / "kb_fwl.bin", HASHED_CATALOG, state=_running(releaseOrder=24))
    p = fw.plan(tmp_path / "kb_fwl.bin", HASHED_CATALOG, state=_running(releaseOrder=24),
                allow_older=True)
    assert p.target["releaseOrder"] == 9


def test_reflashing_the_running_image_is_not_a_downgrade_by_release_order(tmp_path):
    (tmp_path / "kb_fwl.bin").write_bytes(NEW_BYTES)
    p = fw.plan(tmp_path / "kb_fwl.bin", HASHED_CATALOG, state=_running(releaseOrder=24))
    assert p.target["releaseOrder"] == 24


def test_unknown_order_both_ways_is_not_treated_as_a_downgrade(tmp_path):
    """A running image the catalogue knows but cannot order (no version, no release order) does
    not block a write on its own; the side, generation and hash interlocks still stand."""
    (tmp_path / "kb_fwl.bin").write_bytes(OLD_BYTES)
    st = _running(createFirmware=None)
    st["images"][0].pop("releaseOrder", None)
    assert fw.plan(tmp_path / "kb_fwl.bin", HASHED_CATALOG, state=st).target["releaseOrder"] == 9


# --- the resource is a whole slot with its swap trailer already written --------------------- #
# Every keyboard image Naya ships ends with image_ok = 0x01 and BOOT_MAGIC: uploaded whole, that
# schedules a PERMANENT swap the moment the last chunk lands (review of 2026-09-16). The default
# flash uploads only the MCUboot image and writes the trailer itself after the slot check;
# vendor_trailer=True does what NayaCore does.

import struct


def _mcuboot_resource(img=b"\x5a" * 1000, slot_size=4096, trailer="permanent"):
    """A synthetic slot-sized resource: 32-byte header, payload, one TLV area with a SHA-256,
    0xFF padding, and (optionally) the vendor's trailer. Returns (bytes, mcuboot image length)."""
    hdr = struct.pack("<IIHHII", fw.IMAGE_MAGIC, 0, 32, 0, len(img), 4) + b"\0" * 12
    tlv = struct.pack("<HH", fw.TLV_INFO_MAGIC, 40) + struct.pack("<HH", 0x10, 32) + hashlib.sha256(img).digest()
    image = hdr + img + tlv
    body = bytearray(image + b"\xff" * (slot_size - len(image)))
    if trailer:
        body[-24] = 0x01 if trailer == "permanent" else 0xFF
        body[-16:] = fw.BOOT_MAGIC
    return bytes(body), len(image)


def test_a_resource_is_parsed_into_its_image_and_its_trailer():
    res, n = _mcuboot_resource()
    assert n == 32 + 1000 + 40 and fw.mcuboot_image_length(res) == n
    assert fw.image_trailer(res) == {"magic": "good", "imageOk": True, "swap": "permanent"}
    assert fw.image_trailer(_mcuboot_resource(trailer="test")[0])["swap"] == "test"
    assert fw.image_trailer(_mcuboot_resource(trailer=None)[0]) == {"magic": "unset", "imageOk": False, "swap": None}
    assert fw.mcuboot_image_length(b"\x00" * 4096) is None      # no header: nothing to trim


def _resource_catalog(res):
    return [{"file": "kb_fwl.bin", "side": "left", "generation": "A", "createFirmware": "3.41.0",
             "plaintextSha256": RUNNING_HASH, "blobSha256": _sha(res), "flashable": True,
             "withheldBecause": []}]


def test_the_image_only_path_uploads_only_the_image_and_schedules_after_the_check(tmp_path, monkeypatch):
    """vendor_trailer=False: the sequence that is better on paper and has never met a board.

    It was the default until SCRUM-106. A default should be the path that has been run, and
    every real flash has used the vendor's own bytes -- so this one is now opt-in, to be tried
    deliberately on a board someone is prepared to recover rather than because a signature said
    so. It is kept, and kept tested, because the argument for it is unchanged.
    """
    res, n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    r = fw.flash(tmp_path / "kb_fwl.bin", _resource_catalog(res), arm=RUNNING_HASH, state=state_ok(),
                 vendor_trailer=False)
    chunks = [b for h, b in log if h == {"op": 2, "group": 1, "id": 1}]
    assert chunks[0]["len"] == n and sum(len(c["data"]) for c in chunks) == n < len(res)
    assert len(chunks) == -(-n // fw.DEFAULT_CHUNK) and fw.DEFAULT_CHUNK == 512
    assert _kinds(log)[-3:] == [(1, 0, 0), (1, 0, 2), (0, 5, 2)], "check, then schedule, then reset"
    assert r["swap"] == "test" and r["trailer"]["swap"] == "permanent" and r["armedByUpload"] is False
    assert r["written"] == n and r["ofFile"] == len(res)


def test_the_vendor_trailer_is_the_default_and_writes_no_image_state(tmp_path, monkeypatch):
    """The whole resource, as NayaCore uploads it -- and as every flash this project has run on
    hardware did (2026-09-20). Called here with no vendor_trailer argument at all, which is the
    point: the default is the path with evidence behind it (SCRUM-106)."""
    res, n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    p = fw.plan(tmp_path / "kb_fwl.bin", _resource_catalog(res), state=state_ok())
    assert p.vendor_trailer is True
    assert p.arms_on_upload and p.total_bytes == len(res) and "as NayaCore does" in p.describe()
    r = fw.flash(tmp_path / "kb_fwl.bin", _resource_catalog(res), arm=RUNNING_HASH, state=state_ok(),
                 confirm=False)
    chunks = [b for h, b in log if h == {"op": 2, "group": 1, "id": 1}]
    assert chunks[0]["len"] == len(res) and sum(len(c["data"]) for c in chunks) == len(res)
    assert (1, 0, 2) not in _kinds(log), "no image state write: the trailer already scheduled it"
    assert _kinds(log)[-2:] == [(1, 0, 0), (0, 5, 2)]
    assert r["swap"].startswith("permanent (by the resource") and r["armedByUpload"] is True


def test_a_mismatch_after_a_vendor_trailer_upload_says_what_is_armed(tmp_path, monkeypatch):
    res, _n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []
    _patch_transport(monkeypatch, _fake_bootloader("ab" * 32, log))
    with pytest.raises(fw.UploadRefused, match="swap IS scheduled"):
        fw.flash(tmp_path / "kb_fwl.bin", _resource_catalog(res), arm=RUNNING_HASH, state=state_ok(),
                 vendor_trailer=True)
    assert (0, 5, 2) not in _kinds(log)


def test_a_bootloader_that_reports_not_pending_after_the_write_stops_before_reset(tmp_path, monkeypatch):
    res, _n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []

    def talk(port, frame, timeout=2.0):
        h, b = _decode_header(frame), _decode_request(frame)
        log.append((h, b))
        if h == {"op": 2, "group": 1, "id": 1}:
            return {"rc": 0, "off": b["off"] + len(b["data"])}
        if h == {"op": 0, "group": 1, "id": 0}:
            return {"images": [{"slot": 0, "hash": bytes.fromhex(RUNNING_HASH)},
                               {"slot": 1, "hash": bytes.fromhex(RUNNING_HASH)}]}
        if h == {"op": 2, "group": 1, "id": 0}:
            return {"images": [{"slot": 1, "hash": bytes.fromhex(RUNNING_HASH), "pending": False,
                                "confirmed": False, "active": False}]}
        return {"rc": 0}
    _patch_transport(monkeypatch, talk)
    with pytest.raises(fw.UploadRefused, match="not pending"):
        # The image-only path is the one that writes `image state` and can be told "not pending".
        fw.flash(tmp_path / "kb_fwl.bin", _resource_catalog(res), arm=RUNNING_HASH,
                 state=state_ok(), vendor_trailer=False)
    assert (0, 5, 2) not in _kinds(log)


def test_the_primary_slot_is_never_an_upload_target(images):
    """Reviewer's finding: nothing refused slot=0, whose upload id addresses the image the half
    boots from."""
    with pytest.raises(fw.UploadRefused, match="PRIMARY"):
        fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok(), slot=0)
    with pytest.raises(fw.UploadRefused, match="not a place"):
        fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok(), slot=2)


# --- how an upload is addressed: the device's slot map first, the assumption second ---------- #
# MCUboot's serial recovery does not number upload targets the way application-side mcumgr does
# (see the note at the top of firmware_upload.py). The device's `image slot info` answer is the
# authority; without one the plan uses the direct-upload scheme and SAYS it is an assumption.

SLOT_MAP = {"supported": True, "rc": 0, "slots": [
    {"image": 0, "slot": 0, "size": 663552, "uploadImageId": 1},
    {"image": 0, "slot": 1, "size": 663552, "uploadImageId": 2},
    {"image": 1, "slot": 0, "size": 1048576, "uploadImageId": 3},
]}


def test_without_a_slot_map_the_secondary_slot_is_the_assumed_direct_id_and_says_so(images):
    p = fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok())
    assert p.upload_image_id == 2 and p.upload_id_source.startswith("assumed")
    assert "assumed" in p.describe()


def test_the_devices_own_upload_id_wins_over_the_assumption(images):
    custom = {"supported": True, "slots": [{"image": 0, "slot": 1, "size": 663552, "uploadImageId": 9}]}
    p = fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok(), slot_info=custom)
    assert (p.upload_image_id, p.upload_id_source) == (9, "device slot info")
    st = state_ok()
    st["slotInfo"] = custom                     # as read_running_image() carries it
    assert fw.plan(images / "kb_fwl.bin", CATALOG, state=st).upload_image_id == 9


def test_an_image_larger_than_its_slot_is_refused_before_anything_is_sent(images):
    small = {"supported": True, "slots": [{"image": 0, "slot": 1, "size": 1024, "uploadImageId": 2}]}
    with pytest.raises(fw.UploadRefused, match="slot 1 is 1024"):
        fw.plan(images / "kb_fwl.bin", CATALOG, state=state_ok(), slot_info=small)


def test_upload_frames_carry_the_resolved_image_id(images, monkeypatch):
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    nine = {"supported": True, "slots": [{"image": 0, "slot": 1, "size": 663552, "uploadImageId": 9}]}
    fw.flash(images / "kb_fwl.bin", CATALOG, arm=RUNNING_HASH, state=state_ok(), chunk=1024,
             slot_info=nine)
    chunks = [b for h, b in log if h == {"op": 2, "group": 1, "id": 1}]
    assert len(chunks) == 4 and all(b["image"] == 9 for b in chunks)
    assert (1, 6, 0) not in _kinds(log), "a map passed in is not re-read"


# --- the module bundle: FlashMemory.bin into the modules slot ------------------------------- #
# Not an MCUboot image: no mark-pending and no hash to read back. Its upload id is NayaCore's
# constant 4 (uploadImageToModulesSlot -> uploadImageToSlot(_, 4), both mac builds), used only
# after the device's own slot map has shown it numbers the secondary slot 2, the way NayaCore's
# Create constant assumes. BOARD_MAP is what the owner's board answered on 2026-09-16.

BUNDLE_BYTES = bytes(range(256)) * 4096          # 1048576 B, the partition's size
MODULE_CATALOG = CATALOG + [
    {"file": "FlashMemory.bin", "target": "module", "type": "littlefs", "component": "modules",
     "blobSha256": _sha(BUNDLE_BYTES), "moduleFirmware": "2.3.3", "versionLabel": "2.3.3",
     "bundle": "NayaFlow 1.25.1", "releaseOrder": 24, "flashable": True, "withheldBecause": [],
     "contents": {"Touch_UserApp.sfb": {"sha256": "aa" * 32, "size": 1}}},
]
BOARD_MAP = {"supported": True, "rc": 0, "slots": [
    {"image": 0, "slot": 0, "size": 663552, "uploadImageId": 1},
    {"image": 0, "slot": 1, "size": 663552, "uploadImageId": 2},
]}
MODULE_MAP = BOARD_MAP
BIG_CHUNK = fw.MAX_CHUNK                          # 256 chunks of the 1 MiB bundle
BUNDLE_CHUNKS = len(BUNDLE_BYTES) // BIG_CHUNK


def test_a_chunk_that_cannot_be_framed_is_refused_up_front():
    with pytest.raises(ValueError, match="16-bit length"):
        fw.build_chunk_request(2, 0, b"\x00" * (fw.MAX_CHUNK + 1), total=1, sha=b"\x00" * 32)
    with pytest.raises(ValueError, match="1 to"):
        fw.build_chunk_request(2, 8, b"")


@pytest.fixture()
def bundle(tmp_path):
    p = tmp_path / "FlashMemory.bin"
    p.write_bytes(BUNDLE_BYTES)
    return p


def test_a_bundle_needs_the_devices_slot_map(bundle):
    with pytest.raises(fw.UploadRefused, match="slot map"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok())
    with pytest.raises(fw.UploadRefused, match="slot map"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(),
                              slot_info={"supported": False, "rc": 8, "slots": []})


def test_the_modules_slot_is_nayacores_4_once_the_device_confirms_the_numbering(bundle):
    p = fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=BOARD_MAP)
    assert p.upload_image_id == fw.MODULES_UPLOAD_IMAGE_ID == 4
    assert p.slot["source"].startswith("NayaCore constant") and p.expected_version == "2.3.3"
    assert p.arm_token == RUNNING_HASH and "upload image id 4" in p.describe()


def test_a_bootloader_that_numbers_differently_gets_no_vendor_constant(bundle):
    """If the device's map gave the secondary slot any id but 2, NayaCore's 4 means nothing on
    it. Refuse rather than write into whatever 4 addresses there."""
    odd = {"supported": True, "slots": [{"image": 0, "slot": 0, "size": 663552, "uploadImageId": 0},
                                        {"image": 0, "slot": 1, "size": 663552, "uploadImageId": 1}]}
    with pytest.raises(fw.UploadRefused, match="numbering is not understood"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=odd)
    missing = {"supported": True, "slots": [{"image": 0, "slot": 0, "size": 663552}]}
    with pytest.raises(fw.UploadRefused, match="numbering is not understood"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=missing)


def test_a_map_that_lists_a_bundle_sized_slot_wins_over_the_constant(bundle):
    listed = {"supported": True, "slots": BOARD_MAP["slots"]
              + [{"image": 1, "slot": 1, "size": len(BUNDLE_BYTES), "uploadImageId": 7}]}
    p = fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=listed)
    assert p.upload_image_id == 7 and p.slot["source"] == "device slot info"
    two = {"supported": True, "slots": listed["slots"]
           + [{"image": 2, "slot": 0, "size": len(BUNDLE_BYTES), "uploadImageId": 9}]}
    with pytest.raises(fw.UploadRefused, match="2 slots"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=two)


def test_the_keyboards_own_slots_are_never_taken_for_the_modules_slot(bundle):
    """A keyboard slot that happens to be bundle-sized does not become the modules slot."""
    same = {"supported": True, "slots": [{"image": 0, "slot": 0, "size": len(BUNDLE_BYTES), "uploadImageId": 1},
                                         {"image": 0, "slot": 1, "size": len(BUNDLE_BYTES), "uploadImageId": 2}]}
    p = fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=same)
    assert p.upload_image_id == 4


def test_a_bundle_of_the_wrong_size_is_refused(tmp_path):
    small = tmp_path / "FlashMemory.bin"
    small.write_bytes(b"\x07" * 4096)
    cat = MODULE_CATALOG + [dict(MODULE_CATALOG[-1], blobSha256=_sha(b"\x07" * 4096))]
    with pytest.raises(fw.UploadRefused, match="1048576 bytes"):
        fw.plan_module_bundle(small, cat, state=state_ok(), slot_info=BOARD_MAP)


def test_a_bundle_goes_through_the_left_half_only(bundle):
    with pytest.raises(fw.UploadRefused, match="LEFT"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(side="right"),
                              slot_info=MODULE_MAP)
    lying = state_ok()                       # image says left, descriptor says right
    lying.update({"pid": 0x00D3, "pidSide": "right", "pidGeneration": "A"})
    with pytest.raises(fw.UploadRefused, match="Two sources disagree"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=lying, slot_info=MODULE_MAP)


def test_a_bundle_and_a_keyboard_image_refuse_each_others_path(bundle, images):
    with pytest.raises(fw.UploadRefused, match="module firmware, not a keyboard image"):
        fw.plan(bundle, MODULE_CATALOG, state=state_ok())
    with pytest.raises(fw.UploadRefused, match="not a module bundle"):
        fw.plan_module_bundle(images / "kb_fwl.bin", MODULE_CATALOG, state=state_ok(),
                              slot_info=MODULE_MAP)


def test_a_bundle_downgrade_needs_allow_older_when_the_installed_version_is_known(bundle):
    with pytest.raises(fw.UploadRefused, match="older"):
        fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=MODULE_MAP,
                              installed_version="2.4.0")
    p = fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=MODULE_MAP,
                              installed_version="2.4.0", allow_older=True)
    assert p.expected_version == "2.3.3"
    same = fw.plan_module_bundle(bundle, MODULE_CATALOG, state=state_ok(), slot_info=MODULE_MAP,
                                 installed_version="2.3.3")
    assert same.expected_version == "2.3.3"


def test_a_withheld_bundle_is_refused(bundle):
    held = [dict(e, flashable=False, withheldBecause=["module flash path not tested"])
            if e["file"] == "FlashMemory.bin" else e for e in MODULE_CATALOG]
    with pytest.raises(fw.UploadRefused, match="withheld"):
        fw.plan_module_bundle(bundle, held, state=state_ok(), slot_info=MODULE_MAP)


def test_flash_module_bundle_is_chunks_then_reset_and_nothing_else(bundle, monkeypatch):
    """No mark-pending and no slot re-read: the bundle is a filesystem, not an MCUboot image."""
    log = []
    _patch_transport(monkeypatch, _fake_bootloader(RUNNING_HASH, log))
    r = fw.flash_module_bundle(bundle, MODULE_CATALOG, arm=RUNNING_HASH, state=state_ok(),
                               slot_info=MODULE_MAP, chunk=BIG_CHUNK)
    assert _kinds(log) == [(1, 1, 2)] * BUNDLE_CHUNKS + [(0, 5, 2)]
    assert all(b["image"] == 4 for _h, b in log[:BUNDLE_CHUNKS])
    assert log[0][1]["len"] == len(BUNDLE_BYTES) and log[0][1]["sha"] == hashlib.sha256(BUNDLE_BYTES).digest()
    assert r["reset"] is True and r["uploadImageId"] == 4
    assert r["verifyNext"]["read"] == "MODULE_FILE_FW_VERSION" and r["verifyNext"]["expect"] == "2.3.3"


def test_flash_module_bundle_refuses_without_the_arm_token(bundle, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a frame was sent despite the arm check failing")
    _patch_transport(monkeypatch, boom)
    with pytest.raises(fw.UploadRefused, match="not armed"):
        fw.flash_module_bundle(bundle, MODULE_CATALOG, arm="", state=state_ok(), slot_info=MODULE_MAP)


def test_flash_module_bundle_stops_without_reset_if_the_bootloader_rejects_a_chunk(bundle, monkeypatch):
    log = []

    def talk(port, frame, timeout=2.0):
        h, b = _decode_header(frame), _decode_request(frame)
        log.append((h, b))
        if h == {"op": 2, "group": 1, "id": 1}:
            return {"rc": 3} if b["off"] >= 524288 else {"rc": 0, "off": b["off"] + len(b["data"])}
        return {"rc": 0}
    _patch_transport(monkeypatch, talk)
    with pytest.raises(fw.UploadRefused, match="rejected the chunk at offset 524288"):
        fw.flash_module_bundle(bundle, MODULE_CATALOG, arm=RUNNING_HASH, state=state_ok(),
                               slot_info=MODULE_MAP, chunk=BIG_CHUNK)
    assert (0, 5, 2) not in _kinds(log), "no reset after a refused chunk"


# --- what the first two real flashes taught us, 2026-09-20 ---------------------------------- #
# Both halves of a warranty board went 3.35.4 <-> 3.41.0 through this module. Two things the
# bench had never shown, each of which made flash() refuse a flash that had worked:

TARGET_HASH = "2abb2695b9b6e948" + "cd" * 24          # != RUNNING_HASH, so a swap is detectable


def _post_swap_bootloader(log: list, *, fail_reads: int = 0):
    """MCUboot AFTER it has already carried out the swap the resource's trailer armed.

    The image just written is in slot 0 and the one it replaced has been moved down to slot 1 --
    the exact layout both real flashes reported. Optionally throws on the first `fail_reads`
    state reads, the way the port does while the bootloader is busy acting on the trailer.
    """
    state = {"n": 0}

    def talk(port, frame, timeout=2.0):
        h, body = _decode_header(frame), _decode_request(frame)
        log.append((h, body))
        if h == {"op": 2, "group": 1, "id": 1}:
            return {"rc": 0, "off": body["off"] + len(body["data"])}
        if h == {"op": 0, "group": 1, "id": 0}:
            state["n"] += 1
            if state["n"] <= fail_reads:
                raise OSError("ClearCommError failed (the device does not recognize the command)")
            return {"images": [{"slot": 0, "hash": bytes.fromhex(TARGET_HASH)},
                               {"slot": 1, "hash": bytes.fromhex(RUNNING_HASH)}]}
        return {"rc": 0}
    return talk


def _target_catalog(res):
    return [{"file": "kb_fwl.bin", "side": "left", "generation": "A", "createFirmware": "3.41.0",
             "plaintextSha256": TARGET_HASH, "blobSha256": _sha(res), "flashable": True,
             "withheldBecause": []}]


def test_a_swap_already_carried_out_is_a_success_not_a_corrupt_upload(tmp_path, monkeypatch):
    """A vendor resource arms a PERMANENT swap the moment its trailer lands, and MCUboot can act
    on it before we get to look. Checking only the secondary slot then finds the image we just
    REPLACED and calls a perfect flash corrupt -- and, far worse, skips the reset, leaving the
    half stranded in the bootloader. Measured on both halves of a real board."""
    res, _n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []
    _patch_transport(monkeypatch, _post_swap_bootloader(log))
    r = fw.flash(tmp_path / "kb_fwl.bin", _target_catalog(res), arm=RUNNING_HASH,
                 state=state_ok(), vendor_trailer=True)
    assert "already carried out" in r["swap"] and r["reset"] is True
    assert _kinds(log)[-1] == (0, 5, 2), "the reset must still be sent"
    assert (1, 0, 2) not in _kinds(log), "no image state write: the trailer scheduled it"


def test_the_post_upload_read_waits_the_bootloader_out(tmp_path, monkeypatch):
    """The last chunk is acknowledged and the port then throws for tens of seconds while MCUboot
    acts on the trailer. A single read there failed on both real flashes."""
    res, _n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []
    _patch_transport(monkeypatch, _post_swap_bootloader(log, fail_reads=3))
    monkeypatch.setattr(fw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(fw.rec, "find_recovery_ports", lambda: [])
    r = fw.flash(tmp_path / "kb_fwl.bin", _target_catalog(res), arm=RUNNING_HASH,
                 state=state_ok(), vendor_trailer=True)
    assert r["reset"] is True and _kinds(log)[-1] == (0, 5, 2)


def test_a_bootloader_that_never_answers_after_the_upload_does_not_reset(tmp_path, monkeypatch):
    """Patience is not credulity: if it never comes back, say so and send no reset."""
    res, _n = _mcuboot_resource()
    (tmp_path / "kb_fwl.bin").write_bytes(res)
    log = []

    def _dead(port, frame, timeout=2.0):
        h, body = _decode_header(frame), _decode_request(frame)
        log.append((h, body))
        if h == {"op": 2, "group": 1, "id": 1}:
            return {"rc": 0, "off": body["off"] + len(body["data"])}
        raise OSError("no SMP response")

    _patch_transport(monkeypatch, _dead)
    monkeypatch.setattr(fw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(fw.rec, "find_recovery_ports", lambda: [])
    with pytest.raises(fw.UploadRefused, match="did not answer"):
        fw.flash(tmp_path / "kb_fwl.bin", _target_catalog(res), arm=RUNNING_HASH,
                 state=state_ok(), vendor_trailer=True)
    assert (0, 5, 2) not in _kinds(log), "no reset when what landed could not be checked"
