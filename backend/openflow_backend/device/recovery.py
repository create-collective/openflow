"""MCUboot recovery: see a half that is in the bootloader, and ask it what it is running.

READ-ONLY. Nothing here writes an image. It enumerates recovery-mode devices and performs two
SMP reads -- `os echo` and `image state` -- which is the whole of what the Create's recovery
interface supports anyway: a live probe on 2026-09-01 found `fs` (group 8), enumeration
(group 10), os params and bootloader-info all `ENOTSUP`. Upload exists but is deliberately not
implemented here; see docs and the Phase 6 plan.

WHY THIS MODULE EXISTS AT ALL. A half in recovery re-enumerates as VID 37D1 / PID 006F, which
`_vendor/nayactl/discovery.py` does not know -- so today a half sitting in the bootloader is not
merely unidentified, it is INVISIBLE to OpenFlow. The recovery PID is deliberately NOT added to
the vendored file: that copy is kept byte-for-byte upstream (see _vendor/VENDOR.md) and this is
our concern, not nayactl's. It is a good upstream contribution later.

WHY IT MATTERS. `image state` reports the SHA-256 of the DECRYPTED running image, and
docs/reference/firmware-catalog.json holds that hash for every image we have. So a half can be
asked what it runs and matched against the catalogue -- device-derived identification that works
on a unit whose USB product id we have never seen, which is what any future repair has to be
gated on.

No new dependencies: SMP framing and the small slice of CBOR the image-state response uses are
implemented here rather than pulling in an async SMP stack for two read commands.
"""
from __future__ import annotations

import base64
import contextlib
import struct
import time
from dataclasses import dataclass, field

from serial.tools.list_ports import comports

NAYA_VID = 0x37D1
# THE PRODUCT ID LAYOUT, from NayaCore 6.11.0's Naya_Device::setCreateFlashGenerationFromPid
# (both macOS builds disassembled 2026-09-16): it masks the pid with 0xEFFF and accepts two
# families of three, then reads bit 0x1000 as the flash generation.
#     pid & 0xEFFF   left: 0x064 app, 0x06F MCUboot, 0x07A a third mode
#                    right: 0x0C8 app, 0x0D3 MCUboot, 0x0DE a third mode
#     pid & 0x1000   clear = generation A, set = generation B
# Confirmed on hardware: 0x0064 left app, 0x00C8 right app, 0x006F left in MCUboot, and 0x00D3
# right in MCUboot -- seen on a donor's power-on (2026-09-19, SCRUM-88) and on every right-half
# flash since 2026-09-20, by hand and from the UI. A half in MCUboot presents TWO CDC ports on
# either side (a data port and a log port, not labelled, so both are tried). The third members and
# every generation-B value are still NayaCore's table, not yet seen on hardware. Before this table only 0x006F was looked for, so a right half sitting in its
# bootloader was invisible.
#
# LEAVING RECOVERY. A half that entered MCUboot on RESET/MCU_BOOT does NOT come back on its own:
# on 2026-09-16 the left half sat in the bootloader for well over a minute after the probe
# finished, until an SMP `os reset` (os_reset below) was sent. The 2026-09-01 note that it
# "self-recovers after a few seconds of silence" was wrong. Plan for the reset, or a power cycle.
PID_GEN_B_BIT = 0x1000
# The third member of each family (+22) is accepted by NayaCore but nothing names what it is.
# RESET/DFU exists and would be the natural guess, but the nRF's own DFU bootloader enumerates
# under Nordic's vendor id, not Naya's, so the guess stays a guess: "third", not "dfu".
PID_FAMILY = {
    0x064: ("left", "app"), 0x06F: ("left", "mcuboot"), 0x07A: ("left", "third"),
    0x0C8: ("right", "app"), 0x0D3: ("right", "mcuboot"), 0x0DE: ("right", "third"),
}
RECOVERY_PIDS = frozenset(base | gen for base, (_s, mode) in PID_FAMILY.items()
                          if mode == "mcuboot" for gen in (0, PID_GEN_B_BIT))
RECOVERY_PID = 0x006F          # the left, generation-A value; kept for callers that name it


def pid_info(pid: int | None) -> dict | None:
    """What a Naya product id says: side, mode (app | mcuboot | dfu) and flash generation. None
    for a pid outside NayaCore's own table -- reported as unknown, never guessed."""
    if pid is None:
        return None
    fam = PID_FAMILY.get(pid & ~PID_GEN_B_BIT)
    if fam is None:
        return None
    return {"pid": pid, "side": fam[0], "mode": fam[1],
            "generation": "B" if pid & PID_GEN_B_BIT else "A"}

# SMP (Simple Management Protocol) over the console transport.
SMP_OP_READ = 0
SMP_OP_READ_RSP = 1
SMP_GROUP_OS = 0
SMP_GROUP_IMAGE = 1
SMP_ID_ECHO = 0
SMP_ID_IMAGE_STATE = 0
# `image slot info` (MCUboot boot_serial_priv.h IMGMGR_NMGR_ID_SLOT_INFO): per image and slot, the
# slot's size and, when the bootloader takes direct slot ids for uploads, the `upload_image_id` to
# use. A read; compiled in only with MCUBOOT_SERIAL_IMG_GRP_SLOT_INFO, so ENOTSUP is a normal
# answer and is reported as such rather than raised.
SMP_ID_IMAGE_SLOT_INFO = 6
SMP_ERR_ENOTSUP = 8

# After the first bytes of a reply arrive, how long to wait for the rest. A multi-line SMP
# response comes back-to-back over USB, so this only has to outlast the gap between packets.
# Measured: a complete reply lands 35 ms after its first byte.
RESPONSE_GRACE = 0.03

# How long to let a freshly opened port settle before the first request. Measured: the first
# request after an open often gets no answer at all, while the second and third are fine. Paid
# once per session instead of once per request, which is the whole point of session().
SETTLE_AFTER_OPEN = 0.25


@dataclass
class RecoveryDevice:
    port: str
    description: str = ""
    serial_number: str | None = None
    pid: int | None = None
    side: str | None = None           # from the pid (NayaCore's table), not from anything read
    generation: str | None = None     # likewise: the flash generation the pid encodes


def find_recovery_ports() -> list[RecoveryDevice]:
    """Halves currently sitting in MCUboot recovery, either side, either generation. Read-only;
    opens nothing."""
    out = []
    for p in comports():
        if p.vid == NAYA_VID and p.pid in RECOVERY_PIDS:
            info = pid_info(p.pid) or {}
            out.append(RecoveryDevice(port=p.device, description=p.description or "",
                                      serial_number=getattr(p, "serial_number", None),
                                      pid=p.pid, side=info.get("side"),
                                      generation=info.get("generation")))
    return out


def in_recovery() -> bool:
    return bool(find_recovery_ports())


# A half passes through MCUboot on EVERY power-on, not only when it is stuck there (SCRUM-88).
# Watched on a donor on 2026-09-19: each half enumerated under its MCUboot pid for ~1.6-1.7 s,
# then left for the application on its own. Watched again on the warranty board (3.41.0) on
# 2026-09-22, switching only the RIGHT half on: right at 0x00D3 for 0.98 s, and then the LEFT half,
# untouched, went through MCUboot too (0x006F for 1.40 s, starting 2.2 s after the right). The
# central's re-enumeration when its peer re-links is a reboot, so powering one half on sends both
# through the bootloader, one after the other. One look at the ports cannot tell that from a half
# that is PARKED (entered on RESET/MCU_BOOT, an interrupted flash, an invalid primary), which does
# not leave by itself. So telling a user a half is "in recovery" takes two looks, far enough apart
# that an ordinary boot has finished in between. The flash procedure keeps calling
# find_recovery_ports directly: it put the half there itself and needs to see it at once.
BOOT_PASS_SETTLE_S = 3.0


def still_in_recovery(seen: list[RecoveryDevice], seen_at: float, *,
                      settle: float = BOOT_PASS_SETTLE_S, clock=time.monotonic,
                      sleep=time.sleep) -> list[RecoveryDevice]:
    """Of the halves `seen` in recovery at `seen_at` (a `clock()` reading), the ones still there
    at least `settle` seconds later. Sleeps only for what is left of that interval, and only when
    something was seen: a caller that did other work in between pays nothing, and a board with
    no half in MCUboot never waits. A half that has re-enumerated into the application is gone
    from the second look under its MCUboot pid, which is exactly an ordinary boot."""
    if not seen:
        return []
    left = settle - (clock() - seen_at)
    if left > 0:
        sleep(left)
    now = {(d.port, d.pid) for d in find_recovery_ports()}
    return [d for d in seen if (d.port, d.pid) in now]


# --- CBOR, only as much as the image-state response uses ----------------------------------- #
# Written out rather than adding a dependency: the response is maps, arrays, ints, text, byte
# strings and booleans, and nothing here has to ENCODE anything more complex than an empty map.


def _cbor_decode(b: bytes, i: int = 0):
    """Return (value, next_index). Raises ValueError on anything unexpected."""
    if i >= len(b):
        raise ValueError("truncated CBOR")
    initial = b[i]
    major, extra = initial >> 5, initial & 0x1F
    i += 1
    if extra < 24:
        val = extra
    elif extra == 24:
        val, i = b[i], i + 1
    elif extra == 25:
        val, i = struct.unpack_from(">H", b, i)[0], i + 2
    elif extra == 26:
        val, i = struct.unpack_from(">I", b, i)[0], i + 4
    elif extra == 27:
        val, i = struct.unpack_from(">Q", b, i)[0], i + 8
    elif extra == 31:
        val = None                      # indefinite length
    else:
        raise ValueError(f"bad CBOR additional info {extra}")

    if major == 0:
        return val, i
    if major == 1:
        return -1 - val, i
    if major in (2, 3):
        if val is None:
            raise ValueError("indefinite-length strings not supported")
        raw = b[i:i + val]
        i += val
        return (raw if major == 2 else raw.decode("utf-8", "replace")), i
    if major == 4:
        items = []
        if val is None:
            while b[i] != 0xFF:
                v, i = _cbor_decode(b, i)
                items.append(v)
            return items, i + 1
        for _ in range(val):
            v, i = _cbor_decode(b, i)
            items.append(v)
        return items, i
    if major == 5:
        obj = {}
        if val is None:
            while b[i] != 0xFF:
                k, i = _cbor_decode(b, i)
                v, i = _cbor_decode(b, i)
                obj[k] = v
            return obj, i + 1
        for _ in range(val):
            k, i = _cbor_decode(b, i)
            v, i = _cbor_decode(b, i)
            obj[k] = v
        return obj, i
    if major == 7:
        if extra == 20:
            return False, i
        if extra == 21:
            return True, i
        if extra == 22:
            return None, i
        raise ValueError(f"unsupported CBOR simple value {extra}")
    raise ValueError(f"unsupported CBOR major type {major}")


# --- SMP framing over the serial console ---------------------------------------------------- #
# A request is [header][cbor], CRC16-XMODEM appended, length-prefixed, base64'd, and sent as
# newline-terminated lines: the first starts with 0x06 0x09, continuations with 0x04 0x14.


def _crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# The first header byte is NOT just the op. Bits 0-2 are the op, bits 3-4 are the SMP protocol
# VERSION. Sending version 0 produced a frame this bootloader silently ignored -- no error, no
# reply, indistinguishable from a dead port, and it cost six reboots before the byte was compared
# against a reference client. `smp` builds 08 00 00 01 00 01 00 00 for an image-state read; we
# were building 00 00 00 01 00 01 00 00.
SMP_VERSION = 1


def _smp_header(op: int, group: int, cmd_id: int, payload_len: int, seq: int = 0,
                version: int = SMP_VERSION) -> bytes:
    #  version<<3 | op | flags | length(BE) | group(BE) | seq | id
    return struct.pack(">BBHHBB", ((version & 0x03) << 3) | (op & 0x07), 0,
                       payload_len, group, seq, cmd_id)


def encode_request(op: int, group: int, cmd_id: int, payload: bytes = b"\xa0", seq: int = 0):
    """Frame one SMP request. Default payload is an empty CBOR map."""
    body = _smp_header(op, group, cmd_id, len(payload), seq) + payload
    # The length prefix covers the body AND the trailing CRC -- mcumgr's serial transport sends
    # htons(len + 2). Sending len(body) instead produced a frame the bootloader simply ignored:
    # no error, no reply, which reads exactly like a dead port and cost several reboots to tell
    # apart from one. The CRC being right is not enough if the length is wrong.
    framed = struct.pack(">H", len(body) + 2) + body
    framed += struct.pack(">H", _crc16_xmodem(body))
    b64 = base64.b64encode(framed)
    return b"\x06\x09" + b64 + b"\n"


class ReplyMismatch(ValueError):
    """What arrived answers a different request than the one just sent."""


def _frames(raw: bytes) -> list[bytes]:
    """The base64 of each SMP frame in `raw`: a 06 09 line starts one, 04 14 lines continue it."""
    frames: list[list[bytes]] = []
    for line in raw.split(b"\n"):
        line = line.strip()
        if line.startswith(b"\x06\x09"):
            frames.append([line[2:]])
        elif line.startswith(b"\x04\x14") and frames:
            frames[-1].append(line[2:])
    return [b"".join(f) for f in frames]


def _decode_frame(b64: bytes) -> tuple[tuple[int, int, int], dict]:
    """((group, id, seq), CBOR body) of one frame, or ValueError."""
    framed = base64.b64decode(b64)
    if len(framed) < 4:
        raise ValueError("SMP frame too short")
    body = framed[2:-2]          # strip the length prefix and the CRC
    if _crc16_xmodem(body) != struct.unpack(">H", framed[-2:])[0]:
        raise ValueError("SMP CRC mismatch")
    if len(body) < 8:
        raise ValueError("SMP body too short")
    _op, _flags, _len, group, seq, cid = struct.unpack(">BBHHBB", body[:8])
    value, _ = _cbor_decode(body[8:])
    return (group, cid, seq), (value if isinstance(value, dict) else {"value": value})


def request_key(frame: bytes) -> tuple[int, int, int] | None:
    """(group, id, seq) of a request we built, read back out of its own frame."""
    try:
        return _decode_frame(_frames(frame)[0])[0]
    except (ValueError, IndexError, struct.error):
        return None


def decode_response(raw: bytes, want: tuple[int, int, int] | None = None) -> dict:
    """Pull the CBOR body out of one or more console lines.

    With `want` = the request's (group, id, seq), only a reply to THAT request is returned. The
    bootloader echoes the sequence number, and what arrives on a freshly opened port is not
    always the answer to what was just asked: on 2026-09-23 a late reply to an earlier
    `image state` read (an `images` list with no slots) was taken as the answer to `image slot
    info`, and a slot map the device never sent was reported as "numbering not understood".
    Without `want`, the last frame is returned, as before.
    """
    frames = _frames(raw)
    if not frames:
        raise ValueError("no SMP frame in response")
    if want is None:
        return _decode_frame(frames[-1])[1]
    seen, last_err = [], None
    for b64 in reversed(frames):
        try:
            key, body = _decode_frame(b64)
        except ValueError as e:
            last_err = e
            continue
        if key == want:
            return body
        seen.append(key)
    if seen:
        raise ReplyMismatch(f"no reply to group {want[0]} id {want[1]} seq {want[2]} among "
                            f"{len(frames)} frame(s); got {list(reversed(seen))}")
    raise last_err or ValueError("no SMP frame in response")


# --- the two reads the Create's recovery actually supports ---------------------------------- #


def _talk(port: str, frame: bytes, timeout: float = 2.0) -> dict:
    """One request, one response. Opens and closes the port each time on purpose: the port
    disappears when the half resets (which several of these requests cause), and a fresh handle
    per request is what tells that apart from a dead port.
    """
    import serial
    import time as _time

    # Windows can refuse the port for a moment right after the bootloader enumerates -- an
    # "Access is denied" that clears on its own. Retrying is the difference between testing the
    # data port and never reaching it; a single attempt reported the denial and moved on, so the
    # data port went untested across several probe runs.
    last_open_error = None
    for _attempt in range(4):
        try:
            with serial.Serial(port=port, baudrate=115200, bytesize=serial.EIGHTBITS,
                               parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                               timeout=0.05, dsrdtr=False, write_timeout=timeout) as _probe:
                pass
            break
        except serial.SerialException as e:
            last_open_error = e
            _time.sleep(0.35)
    else:
        # Linux without the udev rule refuses the bootloader's ports as it does the halves'.
        from . import port_access
        if port_access.is_permission_denied(last_open_error):
            raise serial.SerialException(port_access.denied_message(port)) from last_open_error
        raise last_open_error

    # Opened the way the vendored transport opens a Naya CDC port, not with pyserial's defaults.
    # dsrdtr defaults to False in pyserial but the explicit settings matter on Windows: a bare
    # Serial(port, baud) plus reset_input_buffer() fails these ports with "ClearCommError failed
    # / The device does not recognize the command", because the bootloader's CDC does not
    # implement the comm-state queries that call makes. Draining by read instead of by
    # reset_input_buffer avoids the query entirely.
    # 115200 is not what NayaCore uses (it opens at 1,000,000 -- nayaHistory/FLASHING-
    # PROCEDURE.md), and it does not matter: this port is USB CDC-ACM, where the baud setting is
    # cosmetic and bytes move at USB bulk speed. Both slot hashes read correctly at this rate on
    # 2026-09-08. Do not "fix" it into a bug; change it only if a live unit ever proves it matters.
    with serial.Serial(port=port, baudrate=115200,
                       bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                       stopbits=serial.STOPBITS_ONE, timeout=0.1,
                       dsrdtr=False, write_timeout=timeout) as ser:
        ser.dtr = True
        ser.rts = True
        # Bounded drain. An unbounded one can spin on the LOG port, which streams continuously,
        # and every millisecond spent here is spent against a recovery window that closes after
        # a few seconds of SMP silence.
        ser.timeout = 0.02
        for _ in range(3):
            if not ser.read(256):
                break
        ser.write(frame)
        ser.flush()
        # Take what the device actually sent, rather than predicting the shape of the reply.
        #
        # This used to be `ser.read(256)` in a loop with a terminator check, and it cost a FULL
        # TIMEOUT on every request, for two reasons that compounded. read(n) blocks until it has
        # n bytes or times out, and the bootloader answers with 31 -- so we waited out the
        # timeout and then took bytes that had been in the buffer since millisecond one. And the
        # terminator check required the base64 to end with "=" PADDING, which a reply whose
        # length needs none does not, so a COMPLETE response failed the check and sent the loop
        # round for one more full-timeout read.
        #
        # Measured on a live bootloader: the reply to `os echo` lands in 5 ms, 31 bytes, ending
        # in a newline. The old path took 5.000 s for it, to the millisecond, because that was
        # the timeout. A 648 KiB firmware upload ran at 5.06 s per 512-byte chunk -- 1h50 for
        # something NayaCore does in about two minutes over the identical protocol.
        #
        # A silent port still costs the full timeout, which is right: that is the real question
        # being asked of it.
        return _exchange(ser, frame, timeout, port)


def _exchange(ser, frame: bytes, timeout: float, port: str = "") -> dict:
    """One request and its reply on an ALREADY OPEN port.

    Split out of _talk so a bulk transfer can hold one port open across many requests; see
    session(). The reading is deliberately "take what arrived" rather than "read n bytes" or
    "read to a terminator": read(n) blocks until it has n bytes or times out, and a terminator
    check that expected base64 "=" padding failed on complete replies whose length needs none.
    Each of those cost a full timeout per request.
    """
    import time as _time
    want = request_key(frame)
    ser.write(frame)
    ser.flush()
    raw = b""
    last_err: Exception | None = None
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        waiting = ser.in_waiting
        if waiting:
            raw += ser.read(waiting)
            # A multi-line response arrives back-to-back; give the rest a moment to land.
            _time.sleep(RESPONSE_GRACE)
            if not ser.in_waiting:
                # Only the reply to THIS request ends the wait. A stale reply to an earlier one,
                # or a frame still arriving, keeps us listening until the deadline.
                try:
                    return decode_response(raw, want)
                except ValueError as e:
                    last_err = e
        else:
            _time.sleep(0.005)
    if not raw:
        raise TimeoutError(f"no SMP response on {port or ser.port}")
    if last_err is not None:
        raise last_err
    return decode_response(raw, want)


@contextlib.contextmanager
def session(port: str, timeout: float = 5.0):
    """Hold ONE port open and yield `send(frame) -> dict` for many requests.

    For bulk transfer. `_talk` reopens the port per request, which is right for probes -- several
    of them reset the half, and a fresh handle is how that is told apart from a dead port -- and
    wrong for an upload: the bootloader's CDC endpoint needs a moment to settle after an open, so
    reopening 1296 times pays that 1296 times. Measured: the first request after an open often
    times out entirely, while a warm port answers in 78 ms.

    This is the shape the vendor uses ("Open the serial port ... chunked via uploadImageChunk").
    """
    import time as _time
    import serial
    ser = serial.Serial(port=port, baudrate=115200, bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                        timeout=0.1, dsrdtr=False, write_timeout=timeout)
    try:
        ser.dtr = True
        ser.rts = True
        # Let the endpoint settle once, here, instead of once per request.
        _time.sleep(SETTLE_AFTER_OPEN)
        ser.timeout = 0.02
        for _ in range(3):
            if not ser.read(256):
                break
        yield lambda frame, _t=timeout: _exchange(ser, frame, _t, port)
    finally:
        try:
            ser.close()
        except Exception:      # noqa: BLE001 -- closing a port that already went away
            pass


def echo(port: str, text: str = "openflow") -> dict:
    """`os echo`. The cheapest proof that a port is really the SMP data port."""
    payload = b"\xa1" + b"\x61d" + bytes([0x60 | len(text)]) + text.encode()
    return _talk(port, encode_request(2, SMP_GROUP_OS, SMP_ID_ECHO, payload))


def image_state(port: str) -> dict:
    """`image state read` -- what this half is running, and what is in its other slot."""
    return _talk(port, encode_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE))


# --- one held conversation with a bootloader --------------------------------------------------- #

def _open_serial(port: str, timeout: float = 5.0):
    """Open a bootloader port the way _talk does, retrying the refusal Windows gives a port for a
    moment after the bootloader enumerates."""
    import serial
    last = None
    for _attempt in range(6):
        try:
            ser = serial.Serial(port=port, baudrate=115200, bytesize=serial.EIGHTBITS,
                                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                timeout=0.02, dsrdtr=False, write_timeout=timeout)
            ser.dtr = True
            ser.rts = True
            return ser
        except serial.SerialException as e:
            last = e
            time.sleep(0.35)
    from . import port_access
    if port_access.is_permission_denied(last):
        raise serial.SerialException(port_access.denied_message(port)) from last
    raise last


class BootloaderLink:
    """ONE conversation with a half in MCUboot, held the way NayaCore holds it.

    Measured on 2026-09-23 against the warranty board: opening and closing the data port for
    every request made the bootloader answer late and in bursts -- identification took a minute,
    `image slot info` replies arrived 56 s after they were asked for, all at once, and a late
    reply to one request was read as the answer to the next. NayaCore does it differently. Its
    log: "Serial port opened successfully" twice (BOTH of the half's ports), "Log port detected,
    polling serial for boot log until data port worker finishes" -- the console port is read the
    whole time the data port is in use, and both stay open for the visit.

    So: open every port the half presents, find the one that answers SMP, keep it open for every
    request of the visit, and drain the others on a thread, keeping what the console says (the
    bootloader's own account of the visit, for the run log). An unread console can back up; a
    reopened port has to settle each time. This does neither.

        with BootloaderLink("left") as link:
            state = link.image_state()
            link.send(frame, timeout)            # SMP, reply matched to the request
            text = link.console_text()
    """

    def __init__(self, side: str, *, find_timeout: float = 60.0, answer_timeout: float = 2.0,
                 open_fn=None, find_fn=None):
        self.side = side
        self.find_timeout = find_timeout
        self.answer_timeout = answer_timeout
        self._open = open_fn or _open_serial
        self._find = find_fn or find_recovery_ports
        self.device: RecoveryDevice | None = None
        self.port: str | None = None
        self._handles: dict = {}
        self._console = bytearray()
        self._stop = None
        self._thread = None
        self.tries: list[str] = []

    # --- lifecycle ----------------------------------------------------------------------- #

    def __enter__(self) -> "BootloaderLink":
        import threading
        deadline = time.monotonic() + self.find_timeout
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain_loop, name=f"mcuboot-console-{self.side}",
                                        daemon=True)
        self._thread.start()
        while True:
            devs = [d for d in self._find() if d.side == self.side]
            for d in devs:
                if d.port not in self._handles:
                    try:
                        self._handles[d.port] = self._open(d.port)
                    except Exception as e:           # noqa: BLE001 -- retried on the next pass
                        self.tries.append(f"open {d.port}: {type(e).__name__}: {e}")
            for d in devs:
                if d.port not in self._handles:
                    continue
                self.port = d.port                   # the drain thread leaves this one alone
                tee = _Tee(self._handles[d.port])
                try:
                    _exchange(tee, encode_request(SMP_OP_READ, SMP_GROUP_IMAGE,
                                                  SMP_ID_IMAGE_STATE), self.answer_timeout, d.port)
                    self.device = d
                    return self
                except Exception as e:               # noqa: BLE001 -- the console port, or not yet
                    # Whatever the probe read from a port that did not answer is the console's
                    # text -- the bootloader's opening lines -- so it is kept, not thrown away.
                    self._console += tee.seen
                    self.tries.append(f"{d.port}: {type(e).__name__}: {e}")
                    self.port = None
            if time.monotonic() >= deadline:
                self.__exit__(None, None, None)
                raise TimeoutError(f"no {self.side} bootloader port answered SMP within "
                                   f"{self.find_timeout:.0f}s ({'; '.join(self.tries[-4:])})")
            time.sleep(0.5)

    def __exit__(self, *exc) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        for h in list(self._handles.values()):
            try:
                h.close()
            except Exception:                        # noqa: BLE001 -- a port that already went away
                pass
        self._handles.clear()

    def _drain_loop(self) -> None:
        while not self._stop.is_set():
            idle = True
            for port, h in list(self._handles.items()):
                if port == self.port:
                    continue
                try:
                    n = h.in_waiting
                    if n:
                        self._console += h.read(n)
                        idle = False
                except Exception:                    # noqa: BLE001 -- the half may be restarting
                    pass
            if idle:
                time.sleep(0.02)

    # --- requests ------------------------------------------------------------------------ #

    @property
    def serial(self):
        return self._handles.get(self.port)

    def send(self, frame: bytes, timeout: float = 5.0) -> dict:
        return exchange(self, frame, timeout)

    def image_state(self, timeout: float = 5.0) -> dict:
        return self.send(encode_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE), timeout)

    def slot_info(self, timeout: float = 5.0) -> dict:
        return _slot_info_from(self.send(
            encode_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_SLOT_INFO), timeout))

    def reset(self) -> dict:
        try:
            return {"reset": True, "reply": self.send(encode_request(2, SMP_GROUP_OS,
                                                                     SMP_ID_OS_RESET), 2.0)}
        except Exception as e:                       # noqa: BLE001 -- the reset working
            return {"reset": True, "reply": None, "note": f"{type(e).__name__}: {e}"}

    def console_text(self, limit: int = 4000) -> str:
        return bytes(self._console[-limit:]).decode("utf-8", "replace")


class _Tee:
    """A serial handle that remembers what was read through it."""

    def __init__(self, ser):
        self.ser, self.seen = ser, bytearray()

    @property
    def port(self):
        return getattr(self.ser, "port", "")

    @property
    def in_waiting(self):
        return self.ser.in_waiting

    def read(self, n):
        got = self.ser.read(n)
        self.seen += got
        return got

    def write(self, b):
        return self.ser.write(b)

    def flush(self):
        return self.ser.flush()


def exchange(link: "BootloaderLink", frame: bytes, timeout: float) -> dict:
    ser = link.serial
    if ser is None:
        raise TimeoutError("the bootloader link has no data port")
    return _exchange(ser, frame, timeout, link.port or "")


def read_running_image_linked(link: "BootloaderLink", catalog: list | None = None) -> dict:
    """read_running_image, over a held link: the same result, from one open conversation."""
    d = link.device
    state = link.image_state()
    out = {"state": "ok", "port": link.port, "pid": d.pid if d else None,
           "pidSide": d.side if d else None, "pidGeneration": d.generation if d else None,
           "images": []}
    for img in state.get("images") or []:
        h = img.get("hash")
        entry = {"slot": img.get("slot"), "active": bool(img.get("active")),
                 "confirmed": bool(img.get("confirmed")), "version": img.get("version"),
                 "hash": h.hex() if isinstance(h, (bytes, bytearray)) else h}
        entry.update(identify(entry["hash"], catalog))
        out["images"].append(entry)
    try:
        out["slotInfo"] = link.slot_info()
    except Exception as e:                           # noqa: BLE001
        out["slotInfo"] = {"supported": None, "error": f"{type(e).__name__}: {e}", "slots": []}
    return out


SMP_ID_OS_RESET = 5


def os_reset(port: str) -> dict:
    """`os reset`: leave the bootloader and boot the application (the primary image; nothing is
    scheduled by this). The port drops as the half reboots, so a transport error here is the
    reset working, and is returned as {"reset": True, "reply": None} rather than raised."""
    try:
        reply = _talk(port, encode_request(2, SMP_GROUP_OS, SMP_ID_OS_RESET), timeout=2.0)
        return {"reset": True, "reply": reply}
    except Exception as e:                          # noqa: BLE001 -- see docstring
        return {"reset": True, "reply": None, "note": f"{type(e).__name__}: {e}"}


def slot_info(port: str) -> dict:
    """`image slot info` read, normalised: {"supported": bool, "slots": [{"image", "slot",
    "size", "uploadImageId"}], "raw": <reply>}.

    This is the read that settles how an upload must be addressed. MCUboot's serial recovery
    numbers upload targets either by image (default: the PRIMARY slot of image N is written) or,
    with MCUBOOT_SERIAL_DIRECT_IMAGE_UPLOAD, by a direct slot id (2 = the secondary slot of image
    0, 3 = slot2_partition ...). The device answering here with `upload_image_id` per slot removes
    the guess; a slot whose size is exactly the module bundle's 1 MiB is the modules slot. Never
    run on the owner's board before the keyboard is plugged in for step 3 -- it is read-only, but
    recovery mode is a reboot away."""
    return _slot_info_from(_talk(port, encode_request(SMP_OP_READ, SMP_GROUP_IMAGE,
                                                      SMP_ID_IMAGE_SLOT_INFO)))


def _slot_info_from(reply: dict) -> dict:
    """Normalise an `image slot info` reply (see slot_info)."""
    rc = reply.get("rc", 0)
    if rc:
        return {"supported": rc != SMP_ERR_ENOTSUP, "rc": rc, "slots": [], "raw": reply}
    if not reply.get("images"):
        # rc 0 with no slot list is not a map. Seen 2026-09-23 on the warranty board's bootloader,
        # which answered the same read with a full map on 2026-09-16: calling that "supported"
        # made the modules guard read an empty list as a numbering that disagrees with NayaCore.
        # Unanswered is what it is; the caller retries, and the module path then falls back.
        return {"supported": None, "rc": rc, "slots": [], "raw": reply,
                "error": "the reply carried no slot list"}
    slots = []
    for img in reply.get("images") or []:
        for s in img.get("slots") or []:
            slots.append({"image": img.get("image", 0), "slot": s.get("slot"),
                          "size": s.get("size"), "uploadImageId": s.get("upload_image_id")})
    return {"supported": True, "rc": 0, "slots": slots, "raw": reply}


def read_running_image(catalog: list | None = None) -> dict:
    """Find a half in recovery, ask what it runs, and name it against the catalogue.

    Returns a dict that always says what happened, because "no recovery device" and "a device
    that would not answer" need different responses from a caller and must not look alike.
    """
    devices = find_recovery_ports()
    if not devices:
        return {"state": "none", "detail": "No half is in MCUboot recovery."}

    errors = []
    for dev in devices:
        try:
            state = image_state(dev.port)
        except Exception as e:                      # noqa: BLE001 - one port of two is the log
            errors.append(f"{dev.port}: {type(e).__name__}: {e}")
            continue
        images = state.get("images") or []
        # The pid's own claim about this half, beside what the running image will say: two
        # independent sources for side and generation, and the flasher refuses if they differ.
        out = {"state": "ok", "port": dev.port, "pid": dev.pid, "pidSide": dev.side,
               "pidGeneration": dev.generation, "images": []}
        for img in images:
            h = img.get("hash")
            entry = {
                "slot": img.get("slot"),
                "active": bool(img.get("active")),
                "confirmed": bool(img.get("confirmed")),
                "version": img.get("version"),
                "hash": h.hex() if isinstance(h, (bytes, bytearray)) else h,
            }
            entry.update(identify(entry["hash"], catalog))
            out["images"].append(entry)
        # Best effort, and only after the state read succeeded on this port: the slot map is what
        # the flasher addresses uploads by, and "not supported" is a valid, recorded answer.
        try:
            out["slotInfo"] = slot_info(dev.port)
        except Exception as e:                      # noqa: BLE001
            out["slotInfo"] = {"supported": None, "error": f"{type(e).__name__}: {e}", "slots": []}
        return out
    return {"state": "error",
            "detail": "A recovery device is present but neither port answered SMP. Windows can "
                      "refuse the port for a moment after the bootloader enumerates; retry, and "
                      "if it still does not answer, power-cycle the half.",
            "errors": errors}


def identify(image_hash: str | None, catalog: list | None) -> dict:
    """Match a running image hash against the catalogue. Never guesses."""
    if not image_hash:
        return {"identified": False, "why": "the device reported no image hash"}
    for e in catalog or []:
        if e.get("plaintextSha256") == image_hash:
            return {"identified": True, "file": e.get("file"), "side": e.get("side"),
                    "generation": e.get("generation"), "createFirmware": e.get("createFirmware"),
                    "source": e.get("source"), "flashable": e.get("flashable"),
                    # Which NayaFlow release(s) shipped it, and a label that is the firmware
                    # version when a release declared one and the release span otherwise. The
                    # release order is what the downgrade guard compares when the version
                    # number is unknown (most images before 1.14.5 have none).
                    "bundle": e.get("bundle"), "versionLabel": e.get("versionLabel"),
                    "releaseOrder": e.get("releaseOrder"),
                    # "beta" for an image only the NayaFlow beta channel shipped: recognised so
                    # the half can be updated, never offered as a target.
                    "channel": e.get("channel") or "official"}
    return {"identified": False,
            "why": "this image is not one we hold. That is not a fault — it just means we "
                   "cannot say which side or flash generation it is, so nothing may be written "
                   "to this half on the strength of it."}