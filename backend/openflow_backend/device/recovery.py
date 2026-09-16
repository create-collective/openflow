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
import struct
from dataclasses import dataclass, field

from serial.tools.list_ports import comports

NAYA_VID = 0x37D1
# Confirmed live 2026-09-01: entering MCUboot re-enumerates as this PID with TWO CDC ports, a
# data port and a log port. Which is which is not labelled, so both are tried.
RECOVERY_PID = 0x006F

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


@dataclass
class RecoveryDevice:
    port: str
    description: str = ""
    serial_number: str | None = None


def find_recovery_ports() -> list[RecoveryDevice]:
    """Halves currently sitting in MCUboot recovery. Read-only; opens nothing."""
    out = []
    for p in comports():
        if p.vid == NAYA_VID and p.pid == RECOVERY_PID:
            out.append(RecoveryDevice(port=p.device, description=p.description or "",
                                      serial_number=getattr(p, "serial_number", None)))
    return out


def in_recovery() -> bool:
    return bool(find_recovery_ports())


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


def decode_response(raw: bytes) -> dict:
    """Pull the CBOR body out of one or more console lines."""
    chunks = []
    for line in raw.split(b"\n"):
        line = line.strip()
        if line.startswith(b"\x06\x09"):
            chunks = [line[2:]]
        elif line.startswith(b"\x04\x14"):
            chunks.append(line[2:])
    if not chunks:
        raise ValueError("no SMP frame in response")
    framed = base64.b64decode(b"".join(chunks))
    if len(framed) < 4:
        raise ValueError("SMP frame too short")
    body = framed[2:-2]          # strip the length prefix and the CRC
    if _crc16_xmodem(body) != struct.unpack(">H", framed[-2:])[0]:
        raise ValueError("SMP CRC mismatch")
    if len(body) < 8:
        raise ValueError("SMP body too short")
    value, _ = _cbor_decode(body[8:])
    return value if isinstance(value, dict) else {"value": value}


# --- the two reads the Create's recovery actually supports ---------------------------------- #


def _talk(port: str, frame: bytes, timeout: float = 2.0) -> dict:
    """One request, one response. Opens and closes the port each time on purpose.

    Recovery self-recovers after a few seconds of SMP silence and boots the application, so a
    long-lived handle would be a handle to something that has already gone.
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
        ser.timeout = timeout
        ser.write(frame)
        ser.flush()
        raw = b""
        deadline_reads = 0
        while deadline_reads < 40:
            chunk = ser.read(256)
            if chunk:
                raw += chunk
                if b"\n" in raw and (raw.count(b"\n") >= 1 and raw.strip().endswith(b"=")
                                     or raw.count(b"\n") > 1):
                    break
            else:
                deadline_reads += 1
                if raw:
                    break
        if not raw:
            raise TimeoutError(f"no SMP response on {port}")
        return decode_response(raw)


def echo(port: str, text: str = "openflow") -> dict:
    """`os echo`. The cheapest proof that a port is really the SMP data port."""
    payload = b"\xa1" + b"\x61d" + bytes([0x60 | len(text)]) + text.encode()
    return _talk(port, encode_request(2, SMP_GROUP_OS, SMP_ID_ECHO, payload))


def image_state(port: str) -> dict:
    """`image state read` -- what this half is running, and what is in its other slot."""
    return _talk(port, encode_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE))


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
    reply = _talk(port, encode_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_SLOT_INFO))
    rc = reply.get("rc", 0)
    if rc:
        return {"supported": rc != SMP_ERR_ENOTSUP, "rc": rc, "slots": [], "raw": reply}
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
        out = {"state": "ok", "port": dev.port, "images": []}
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
            "detail": "A recovery device is present but neither port answered SMP. Recovery "
                      "boots the application again after a few seconds of silence, so it may "
                      "simply have timed out — put the half back into recovery and retry.",
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
                    "releaseOrder": e.get("releaseOrder")}
    return {"identified": False,
            "why": "this image is not one we hold. That is not a fault — it just means we "
                   "cannot say which side or flash generation it is, so nothing may be written "
                   "to this half on the strength of it."}