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

import pytest

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


def _reply_line(cid: int, payload: bytes, seq: int = 0, group: int = None) -> bytes:
    """A device reply line exactly as the bootloader frames one."""
    import base64
    group = rec.SMP_GROUP_IMAGE if group is None else group
    body = rec._smp_header(rec.SMP_OP_READ_RSP, group, cid, len(payload), seq) + payload
    framed = struct.pack(">H", len(body) + 2) + body + struct.pack(">H", rec._crc16_xmodem(body))
    return b"\x06\x09" + base64.b64encode(framed) + b"\n"


# What the warranty board's bootloader sent on 2026-09-23: an `image state` reply (images, no
# slots) arriving late, then -- sometimes -- the slot map that was actually asked for.
STALE_STATE = _reply_line(rec.SMP_ID_IMAGE_STATE,
                          b"\xa1" + b"\x66images" + b"\x81" + b"\xa1" + b"\x64slot" + b"\x00")
SLOT_MAP = _reply_line(rec.SMP_ID_IMAGE_SLOT_INFO,
                       b"\xa1" + b"\x66images" + b"\x81" + b"\xa2" + b"\x65image" + b"\x00"
                       + b"\x65slots" + b"\x81" + b"\xa3" + b"\x64slot" + b"\x01"
                       + b"\x64size" + b"\x1a\x00\x0a\x20\x00"
                       + b"\x6fupload_image_id" + b"\x02")


def test_a_reply_is_matched_to_the_request_that_asked_for_it():
    want = rec.request_key(rec.encode_request(rec.SMP_OP_READ, rec.SMP_GROUP_IMAGE,
                                              rec.SMP_ID_IMAGE_SLOT_INFO))
    assert want == (rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_SLOT_INFO, 0)
    got = rec.decode_response(STALE_STATE + SLOT_MAP, want)
    assert got["images"][0]["slots"][0]["upload_image_id"] == 2
    got = rec.decode_response(SLOT_MAP + STALE_STATE, want)          # order does not matter
    assert got["images"][0]["slots"][0]["upload_image_id"] == 2
    with pytest.raises(rec.ReplyMismatch, match="group 1 id 6"):
        rec.decode_response(STALE_STATE, want)                        # the 2026-09-23 case
    # without a request to match, the old behaviour: the last frame
    assert "slots" not in rec.decode_response(SLOT_MAP + STALE_STATE)["images"][0]


def test_the_sequence_number_matters_for_upload_chunks():
    def ack(seq):                                                     # image upload is id 1
        return _reply_line(1, b"\xa2" + b"\x62rc" + b"\x00" + b"\x63off" + b"\x19\x02\x00", seq=seq)
    with pytest.raises(rec.ReplyMismatch):
        rec.decode_response(ack(4), (rec.SMP_GROUP_IMAGE, 1, 5))      # last chunk's ack, stale
    assert rec.decode_response(ack(4) + ack(5), (rec.SMP_GROUP_IMAGE, 1, 5))["off"] == 512


class _Serial:
    """A port that delivers `chunks` one per poll, as a bootloader's USB endpoint does. A None
    is a poll on which nothing has arrived yet: the gap between a stale reply and the real one."""

    def __init__(self, chunks):
        self.chunks, self.written, self.port = list(chunks), b"", "COM27"

    def write(self, b):
        self.written += b

    def flush(self):
        pass

    @property
    def in_waiting(self):
        if self.chunks and self.chunks[0] is None:
            self.chunks.pop(0)
            return 0
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, n):
        return self.chunks.pop(0) if self.chunks else b""


def test_exchange_keeps_listening_past_a_stale_reply(monkeypatch):
    monkeypatch.setattr(rec, "RESPONSE_GRACE", 0.0)
    ser = _Serial([STALE_STATE, None, SLOT_MAP])
    frame = rec.encode_request(rec.SMP_OP_READ, rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_SLOT_INFO)
    got = rec._exchange(ser, frame, timeout=2.0)
    assert got["images"][0]["slots"][0]["upload_image_id"] == 2


def test_exchange_with_only_a_stale_reply_says_so_instead_of_returning_it(monkeypatch):
    monkeypatch.setattr(rec, "RESPONSE_GRACE", 0.0)
    ser = _Serial([STALE_STATE])
    frame = rec.encode_request(rec.SMP_OP_READ, rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_SLOT_INFO)
    with pytest.raises(rec.ReplyMismatch):
        rec._exchange(ser, frame, timeout=0.3)


class _SmpPort:
    """A bootloader data port: answers each request it is sent, matched by group/id/seq."""

    def __init__(self, answers):
        self.answers, self.out, self.closed, self.port = answers, b"", False, "COM27"

    def write(self, frame):
        g, cid, seq = rec.request_key(frame)
        payload = self.answers.get((g, cid))
        if payload is not None:
            self.out += _reply_line(cid, payload, seq=seq, group=g)

    def flush(self):
        pass

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n):
        got, self.out = self.out[:n], self.out[n:]
        return got

    def close(self):
        self.closed = True


class _ConsolePort(_SmpPort):
    """The other port: takes the frame, says nothing to it, and prints boot text."""

    def __init__(self, text):
        super().__init__({})
        self.out, self.port = text, "COM26"


def _devices():
    return [rec.RecoveryDevice(port="COM26", pid=0x6F, side="left", generation="A"),
            rec.RecoveryDevice(port="COM27", pid=0x6F, side="left", generation="A")]


def test_a_held_link_finds_the_smp_port_and_keeps_the_console_drained(monkeypatch):
    monkeypatch.setattr(rec, "RESPONSE_GRACE", 0.0)
    state_payload = b"\xa1" + b"\x66images" + b"\x81" + b"\xa1" + b"\x64slot" + b"\x00"
    slot_payload = (b"\xa1" + b"\x66images" + b"\x81" + b"\xa2" + b"\x65image" + b"\x00"
                    + b"\x65slots" + b"\x81" + b"\xa3" + b"\x64slot" + b"\x01"
                    + b"\x64size" + b"\x1a\x00\x0a\x20\x00" + b"\x6fupload_image_id" + b"\x02")
    smp = _SmpPort({(rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_STATE): state_payload,
                    (rec.SMP_GROUP_IMAGE, rec.SMP_ID_IMAGE_SLOT_INFO): slot_payload})
    console = _ConsolePort(b"*** Booting MCUboot 9ddeffa8169c ***\r\nI: Starting bootloader\r\n")
    ports = {"COM26": console, "COM27": smp}
    link = rec.BootloaderLink("left", find_timeout=5.0, answer_timeout=0.3,
                              open_fn=lambda p: ports[p], find_fn=_devices)
    with link:
        assert link.port == "COM27" and link.device.port == "COM27"
        assert link.slot_info()["slots"][0]["uploadImageId"] == 2
        assert link.image_state()["images"][0]["slot"] == 0
        import time as _t
        for _ in range(100):
            if "Starting bootloader" in link.console_text():
                break
            _t.sleep(0.02)
        assert "Booting MCUboot" in link.console_text()
    assert smp.closed and console.closed


def test_a_link_that_finds_no_answering_port_says_so(monkeypatch):
    monkeypatch.setattr(rec, "RESPONSE_GRACE", 0.0)
    ports = {"COM26": _ConsolePort(b""), "COM27": _ConsolePort(b"")}
    link = rec.BootloaderLink("left", find_timeout=0.5, answer_timeout=0.1,
                              open_fn=lambda p: ports[p], find_fn=_devices)
    with pytest.raises(TimeoutError, match="no left bootloader port answered SMP"):
        link.__enter__()
    assert all(p.closed for p in ports.values())


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


# --- the product id table (NayaCore's setCreateFlashGenerationFromPid, both mac builds) ---- #

def test_pid_info_decodes_side_mode_and_generation_the_way_nayacore_does():
    assert rec.pid_info(0x0064) == {"pid": 0x0064, "side": "left", "mode": "app", "generation": "A"}
    assert rec.pid_info(0x00C8) == {"pid": 0x00C8, "side": "right", "mode": "app", "generation": "A"}
    assert rec.pid_info(0x006F) == {"pid": 0x006F, "side": "left", "mode": "mcuboot", "generation": "A"}
    assert rec.pid_info(0x00D3)["side"] == "right" and rec.pid_info(0x00D3)["mode"] == "mcuboot"
    # the +22 members are accepted by NayaCore; what mode they are is not named anywhere
    assert rec.pid_info(0x007A)["mode"] == "third" and rec.pid_info(0x00DE)["mode"] == "third"
    # bit 0x1000 is the flash generation; the family is unchanged
    assert rec.pid_info(0x1064) == {"pid": 0x1064, "side": "left", "mode": "app", "generation": "B"}
    assert rec.pid_info(0x10D3) == {"pid": 0x10D3, "side": "right", "mode": "mcuboot", "generation": "B"}
    # outside the table: unknown, not guessed (the dongle 0x012C, a random pid, nothing)
    assert rec.pid_info(0x012C) is None and rec.pid_info(0x0065) is None and rec.pid_info(None) is None


def test_recovery_scan_sees_either_half_and_either_generation(monkeypatch):
    """Before the table only 0x006F (left, gen A) was looked for; a right half in its bootloader
    was invisible, which is the one moment it most needs to be seen."""
    class P:
        def __init__(self, device, vid, pid):
            self.device, self.vid, self.pid, self.description, self.serial_number = device, vid, pid, "", None
    ports = [P("COM4", 0x37D1, 0x006F), P("COM7", 0x37D1, 0x00D3), P("COM8", 0x37D1, 0x10D3),
             P("COM6", 0x37D1, 0x0064), P("COM3", 0x35EF, 0x0012), P("COM11", 0x37D1, 0x012C)]
    monkeypatch.setattr(rec, "comports", lambda: ports)
    got = rec.find_recovery_ports()
    assert [(d.port, d.side, d.generation) for d in got] == [
        ("COM4", "left", "A"), ("COM7", "right", "A"), ("COM8", "right", "B")]
    assert rec.RECOVERY_PID in rec.RECOVERY_PIDS and len(rec.RECOVERY_PIDS) == 4


# --- a sighting is not a stuck half (SCRUM-88) ---------------------------------------------- #
# Every half passes through MCUboot for ~1.7 s on an ordinary power-on. These pin that a status
# read reports only a half still there on a second look, and that the look costs nothing when
# no half is in the bootloader at all.

class _Port:
    def __init__(self, device, pid):
        self.device, self.vid, self.pid, self.description, self.serial_number = device, 0x37D1, pid, "", None


class _Clock:
    def __init__(self, t=100.0):
        self.t, self.slept = t, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _scans(monkeypatch, *snapshots):
    """comports() answers each snapshot in turn, then the last one forever."""
    calls = []

    def comports():
        calls.append(1)
        return snapshots[min(len(calls), len(snapshots)) - 1]
    monkeypatch.setattr(rec, "comports", comports)
    return calls


def test_an_ordinary_power_on_is_not_reported_as_recovery(monkeypatch):
    """The donor's own timeline: the right half at 0x00D3 on COM17, then the application at
    0x00C8 on COM21 under a different port name."""
    _scans(monkeypatch, [_Port("COM17", 0x00D3)], [_Port("COM21", 0x00C8)])
    clock = _Clock()
    seen, at = rec.find_recovery_ports(), clock()
    clock.t += 0.4                                  # the status read took 0.4 s
    assert rec.still_in_recovery(seen, at, clock=clock, sleep=clock.sleep) == []
    assert len(clock.slept) == 1 and abs(clock.slept[0] - (rec.BOOT_PASS_SETTLE_S - 0.4)) < 1e-9


def test_a_parked_half_is_reported_and_the_read_time_counts(monkeypatch):
    parked = [_Port("COM17", 0x00D3), _Port("COM18", 0x00D3)]
    _scans(monkeypatch, parked, parked)
    clock = _Clock()
    seen, at = rec.find_recovery_ports(), clock()
    clock.t += 5.0                                  # a verbose read outlasted the settle time
    got = rec.still_in_recovery(seen, at, clock=clock, sleep=clock.sleep)
    assert [(d.port, d.side) for d in got] == [("COM17", "right"), ("COM18", "right")]
    assert clock.slept == []                        # no wait on top of a read that was long enough


def test_no_half_in_the_bootloader_costs_no_wait_and_no_second_scan(monkeypatch):
    calls = _scans(monkeypatch, [_Port("COM21", 0x00C8)])
    clock = _Clock()
    seen, at = rec.find_recovery_ports(), clock()
    assert rec.still_in_recovery(seen, at, clock=clock, sleep=clock.sleep) == []
    assert clock.slept == [] and len(calls) == 1


def test_only_a_half_seen_both_times_is_reported(monkeypatch):
    """The left half booted through; the right half is parked; a third port that turned up
    between the looks was never seen twice, so it is not reported yet."""
    _scans(monkeypatch,
           [_Port("COM17", 0x006F), _Port("COM19", 0x00D3)],
           [_Port("COM19", 0x00D3), _Port("COM23", 0x0064), _Port("COM25", 0x006F)])
    clock = _Clock()
    seen, at = rec.find_recovery_ports(), clock()
    got = rec.still_in_recovery(seen, at, clock=clock, sleep=clock.sleep)
    assert [(d.port, d.side) for d in got] == [("COM19", "right")]


def test_slot_info_is_an_image_group_read_with_id_6_and_is_normalised(monkeypatch):
    """`image slot info` (MCUboot IMGMGR_NMGR_ID_SLOT_INFO = 6) is the read that says how uploads
    are addressed; its answer is flattened to one row per slot with the device's upload id."""
    import base64
    import struct
    sent = []

    def talk(port, frame, timeout=2.0):
        sent.append(frame)
        return {"images": [
            {"image": 0, "slots": [{"slot": 0, "size": 663552, "upload_image_id": 1},
                                   {"slot": 1, "size": 663552, "upload_image_id": 2}],
             "max_image_size": 663040},
            {"image": 1, "slots": [{"slot": 0, "size": 1048576, "upload_image_id": 3}]}]}
    monkeypatch.setattr(rec, "_talk", talk)
    got = rec.slot_info("COM9")
    body = base64.b64decode(sent[0][2:-1])[2:-2]
    assert (body[0] & 7, struct.unpack(">H", body[4:6])[0], body[7]) == (0, 1, 6)
    assert got["supported"] and [s["uploadImageId"] for s in got["slots"]] == [1, 2, 3]
    assert got["slots"][2] == {"image": 1, "slot": 0, "size": 1048576, "uploadImageId": 3}


@pytest.mark.parametrize("reply", [{}, {"rc": 0}, {"images": []}])
def test_a_slot_info_reply_with_no_slot_list_is_not_a_map(monkeypatch, reply):
    """2026-09-23: the warranty board's bootloader answered rc 0 with no slots, and counting that
    as a map made the modules guard refuse over a numbering it had never seen."""
    monkeypatch.setattr(rec, "_talk", lambda *a, **k: reply)
    got = rec.slot_info("COM9")
    assert got["supported"] is None and got["slots"] == [] and "no slot list" in got["error"]


def test_slot_info_not_supported_is_an_answer_not_an_error(monkeypatch):
    monkeypatch.setattr(rec, "_talk", lambda *a, **k: {"rc": 8})
    assert rec.slot_info("COM9") == {"supported": False, "rc": 8, "slots": [], "raw": {"rc": 8}}


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
