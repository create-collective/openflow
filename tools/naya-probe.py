#!/usr/bin/env python3
"""naya-probe: what is plugged in, what each half runs, and what sits in its two flash slots.

READ-ONLY. This never resets, flashes, pairs or writes anything. It opens the keyboard's serial
ports, asks questions, and prints the answers. Unplugging it mid-run costs nothing.

    pip install pyserial
    python naya-probe.py                 # probe everything, write naya-probe-<time>.json
    python naya-probe.py --watch-log 20  # also listen to a bootloader's console for 20 s
                                         #   (unplug/replug the half while it listens to
                                         #    capture MCUboot's boot messages)
    python naya-probe.py --bootloader right
                                         # the one exception to read-only: RESTARTS the right
                                         #   half into its bootloader, reads both flash slots
                                         #   (what is installed, what is waiting, their flags)
                                         #   and the slot sizes, then restarts it back into
                                         #   its application. Two restarts; nothing is written
                                         #   to flash. It is what to run after a firmware
                                         #   update that did not take.

What it does
  1. Lists every serial port, decoding Naya's product ids: which half, whether it is running
     its application or sitting in the MCUboot bootloader, and its flash generation (A/B).
  2. For a half running its application: firmware version, its own Bluetooth address, the
     partner address it holds, and the BOND TABLE (allPairs). It also asks for the PARTNER
     half through this port -- a right half whose own USB is dead can still be alive and
     linked, and this is the read that shows it.
  3. For a half in the bootloader (two CDC ports; one speaks SMP, the other is a console):
     `image state` on both ports -- each slot's hash, matched against the known Naya images,
     and its flags; `image slot info` if the bootloader supports it; and whatever the console
     port says.
  4. Writes everything, including raw replies, to naya-probe-<timestamp>.json next to this
     file. Send that file back.

Facts this relies on, all measured on real Creates by the OpenFlow project (traviswye/NayaOS):
  * Naya's USB vendor id is 0x37D1. pid & 0xEFFF: 0x064 left app, 0x06F left MCUboot,
    0x0C8 right app, 0x0D3 right MCUboot; bit 0x1000 set = flash generation B.
  * A half in MCUboot answers SMP on ONE of its two ports; the other is a log port that accepts
    the open and says nothing. Windows can refuse the port for a moment after it enumerates.
  * Right after entering the bootloader the first reads can fail for up to a minute; the
    bootloader is not gone, it is just not answering yet. This probe retries.
  * The SMP header's first byte carries protocol version 1 in bits 3-4. Version 0 is silently
    ignored by this bootloader.
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
    from serial.tools.list_ports import comports
except ImportError:                                   # pragma: no cover
    print("This needs pyserial:  pip install pyserial")
    sys.exit(2)

# ------------------------------------------------------------------------------------------- #
# Naya product ids (NayaCore 6.11.0's own table)
# ------------------------------------------------------------------------------------------- #
NAYA_VID = 0x37D1
PID_GEN_B_BIT = 0x1000
PID_FAMILY = {
    0x064: ("left", "app"), 0x06F: ("left", "mcuboot"), 0x07A: ("left", "third"),
    0x0C8: ("right", "app"), 0x0D3: ("right", "mcuboot"), 0x0DE: ("right", "third"),
}


def pid_info(pid):
    if pid is None:
        return None
    fam = PID_FAMILY.get(pid & ~PID_GEN_B_BIT)
    if fam is None:
        return None
    return {"pid": pid, "side": fam[0], "mode": fam[1],
            "generation": "B" if pid & PID_GEN_B_BIT else "A"}


# Known keyboard images, by the SHA-256 the bootloader reports for a slot (the plaintext image
# hash). From OpenFlow's firmware catalogue, itself built from every NayaFlow release.
KNOWN_IMAGES = {
    "f52aec47c312efb8aa34c373ab313b0331601b12a4ef526ab53684444726fab1": "3.28.7 left gen A",
    "fee82f0e07bc7a54f81701de4b703a4d595a8cd4b10937463be76dbfb28c5c5a": "3.28.7 right gen A",
    "99e6f8b23b16b6a473698b9b95a9d476529756e58aaac40b331522ec321fe5ad": "3.29.1 left gen A",
    "ce0f1317a096fa2f21b7f121bc2405363299baabb9e1666756fcb0624fa90675": "3.29.1 right gen A",
    "1b259d25983bb6db0fba53d191e3dae736ae94dbd1b5b1a0fbee036e09524246": "3.31.1 left gen A",
    "90f98e4d8320b86cb2d122cefaff5c0f22f6b05433ba0939c12685e88ed6ef8a": "3.31.1 right gen A",
    "036059b2ecbd89265bc0dfc9030ccf3c2332d555aed7bf91cfa146d22e8c5979": "3.35.4 left gen A",
    "959fbae1d8359ebee2f23f483f6a49feb3f9e3dd85238637ee4bb7abe3e61a1d": "3.35.4 right gen A",
    "479e89ba6c92ead9c46d1228d5033437caf63d72db89364081b9b0a321b31283": "3.41.0 left gen A",
    "07dd2523bf87ee1385fdfb4dbaacd57c8f928e3751306a3e63eac748b2454297": "3.41.0 left gen B",
    "2abb2695b9b6e94883553e101ea5edb8e1934e3919d62b14e589331fe9f5bcfc": "3.41.0 right gen A",
    "87f63fd3be514538f099803c0912516a54bbb256facf2c50df6c0c85c16a6677": "3.41.0 right gen B",
    # Older releases that declared no firmware version.
    "8c926ca7a710cbebfdb09b29a7320e848091521f8cce36d03e469f02b271898a": "older left gen A image",
    "735878524ad86f7b27e4fd46ecfd90275ce65610c634ea9a0be68882434f6646": "older left gen A image",
    "e3a7afc4e765c631d35aeae4133e611ca529502a6c3cea7e6417f2053e79d76c": "older left gen A image",
    "83100f7b0f58c2abb53ba24378c3ef963e61e2abad2b43df2eecb9ed85e6949a": "older left gen A image",
    "ce51a353d7806494978aa0a1e1d4a199d0fa32c547dc0b97c5d21f8a51dfa09b": "older left gen A image",
    "ce6d82b91b2246feb72505a0addcf93246e543e285b8ca347c56942344011756": "older left gen A image",
    "baa94b1d062ac624b68c60025cfc9908b1533f63c345b883801a5773fd11abac": "older right gen A image",
    "e1577ee8be94501f162e4cd094f5bf43c5cade184064de059ba48f1aa8e41a7d": "older right gen A image",
    "93b050dcf560fa43bce8bb172c252ba4ea1b761aefc425b86c7a362ef4a88c53": "older right gen A image",
    "ec1bbca40c74f91cddb0e1904708363f1199a88f5f6bca555fa15d7e7af13843": "older right gen A image",
    "31ceec1a3bf05a962c713fc55de0110015840942bea5b24908d3859d4f227317": "older right gen A image",
    "066ebb1c07644226daef1c49960723fd1ddfb5210182c1c501b1b82a32ef7f2e": "older right gen A image",
}

# ------------------------------------------------------------------------------------------- #
# The application's CDC protocol (from nayactl, Apache-2.0, Cory Bennett)
# ------------------------------------------------------------------------------------------- #
SOURCE_HOST, EOT = 0xAA, 0x04
DEST = {"left": 0x50, "right": 0x51}
CAT_SYSTEM, CAT_BLE = 0xFE, 0xBE
SYS_MEDIA_ID_REQUEST, SYS_GET_FW_VERSION = 0x1001, 0x1002
BLE_GET_PAIR_ADDRESS, BLE_GET_ALL_PAIRS, BLE_GET_ADDRESS = 0x1002, 0x1005, 0x1008


def xor_checksum(data):
    r = 0
    for b in data:
        r ^= b
    return r


def cdc_build(dest, category, subcmd, payload=b""):
    region = bytes([(subcmd >> 8) & 0xFF, subcmd & 0xFF, 0x00]) + payload
    return (bytes([SOURCE_HOST, 0x00, dest, 0x00, category, len(region)]) + region
            + bytes([xor_checksum(region), EOT]))


def cdc_parse(frame):
    if len(frame) < 11 or frame[-1] != EOT:
        return None
    size = frame[5]
    payload = frame[9:9 + size - 3] if size > 3 else b""
    ok = (6 + size) < len(frame) and xor_checksum(frame[6:6 + size]) == frame[6 + size]
    return {"category": frame[4], "subcmd": (frame[6] << 8) | frame[7], "flags": frame[8],
            "payload": payload, "checksum_ok": ok, "raw": frame.hex()}


def cdc_frames(buf, frames):
    while len(buf) >= 6:
        try:
            start = buf.index(0xAA)
        except ValueError:
            buf.clear()
            break
        if start:
            del buf[:start]
        if len(buf) < 6:
            break
        n = 6 + buf[5] + 2
        if len(buf) < n:
            break
        frame = bytes(buf[:n])
        del buf[:n]
        if frame[-1] == EOT:
            frames.append(frame)
    return buf


def open_port(port, timeout=0.1):
    return serial.Serial(port=port, baudrate=115200, bytesize=serial.EIGHTBITS,
                         parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                         timeout=timeout, dsrdtr=False, write_timeout=2.0)


def cdc_send(ser, frame, timeout=1.0):
    ser.reset_input_buffer()
    ser.write(frame)
    ser.flush()
    frames, buf, t0 = [], bytearray(), time.time()
    while time.time() - t0 < timeout:
        chunk = ser.read(256)
        if chunk:
            buf.extend(chunk)
            buf = cdc_frames(buf, frames)
        elif frames:
            break
    return [f for f in (cdc_parse(x) for x in frames) if f]


def cdc_handshake(ser, dest):
    """MEDIA_ID_REQUEST wakes the CDC channel; GET_FW_VERSION proves it. Retried the way the
    keyboard needs on a first connect."""
    for wait in (0.3, 0.7, 1.0):
        ser.reset_input_buffer()
        ser.write(cdc_build(dest, CAT_SYSTEM, SYS_MEDIA_ID_REQUEST))
        ser.flush()
        time.sleep(wait)
        ser.read(4096)
        got = cdc_send(ser, cdc_build(dest, CAT_SYSTEM, SYS_GET_FW_VERSION), 0.5)
        if got:
            return True
    return False


def fw_version(payload):
    return f"{payload[1]}.{payload[2]}.{payload[3]}" if payload and len(payload) >= 4 else None


def mac(p):
    return ":".join(f"{b:02X}" for b in p[:6]) if p and len(p) >= 6 else None


def app_reads(ser, dest):
    """Version and Bluetooth identity for the half addressed by `dest` through this port."""
    out = {"dest": f"0x{dest:02X}"}

    def ask(cat, sub, name):
        got = cdc_send(ser, cdc_build(dest, cat, sub), 1.5)
        raw = bytes(got[0]["payload"]) if got else None
        out.setdefault("raw", {})[name] = raw.hex() if raw is not None else None
        return raw or None                          # an EMPTY payload is not an answer

    v = ask(CAT_SYSTEM, SYS_GET_FW_VERSION, "fw")
    out["firmwareVersion"] = fw_version(v)
    out["bleAddress"] = mac(ask(CAT_BLE, BLE_GET_ADDRESS, "own"))
    out["pairAddress"] = mac(ask(CAT_BLE, BLE_GET_PAIR_ADDRESS, "pair"))
    allp = ask(CAT_BLE, BLE_GET_ALL_PAIRS, "allPairs")
    peers = []
    if allp and allp[0] <= 8 and len(allp) >= 1 + allp[0] * 6:
        peers = [m for m in (mac(allp[1 + k * 6:7 + k * 6]) for k in range(allp[0])) if m]
    out["allPairs"] = peers if allp else None
    return out


# ------------------------------------------------------------------------------------------- #
# The bootloader's SMP protocol over its console (from OpenFlow's recovery.py)
# ------------------------------------------------------------------------------------------- #
SMP_VERSION = 1
SMP_OP_READ, SMP_GROUP_IMAGE = 0, 1
SMP_ID_IMAGE_STATE, SMP_ID_IMAGE_SLOT_INFO, SMP_ERR_ENOTSUP = 0, 6, 8
SMP_OP_WRITE, SMP_GROUP_OS, SMP_ID_OS_RESET = 2, 0, 5
# The application's "restart into the bootloader" (nayactl CAT_RESET / RESET_MCU_BOOT), the same
# command OpenFlow's firmware procedure sends before an upload.
CAT_RESET, RESET_MCU_BOOT = 0xEE, 0x10AE
RESPONSE_GRACE, SETTLE_AFTER_OPEN = 0.03, 0.25


def crc16_xmodem(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def smp_request(op, group, cmd_id, payload=b"\xa0", seq=0):
    body = struct.pack(">BBHHBB", ((SMP_VERSION & 0x03) << 3) | (op & 0x07), 0,
                       len(payload), group, seq, cmd_id) + payload
    framed = struct.pack(">H", len(body) + 2) + body + struct.pack(">H", crc16_xmodem(body))
    return b"\x06\x09" + base64.b64encode(framed) + b"\n"


def cbor_decode(b, i=0):
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
        val = None
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
                v, i = cbor_decode(b, i)
                items.append(v)
            return items, i + 1
        for _ in range(val):
            v, i = cbor_decode(b, i)
            items.append(v)
        return items, i
    if major == 5:
        obj = {}
        if val is None:
            while b[i] != 0xFF:
                k, i = cbor_decode(b, i)
                v, i = cbor_decode(b, i)
                obj[k] = v
            return obj, i + 1
        for _ in range(val):
            k, i = cbor_decode(b, i)
            v, i = cbor_decode(b, i)
            obj[k] = v
        return obj, i
    if major == 7:
        return {20: False, 21: True, 22: None}[extra], i
    raise ValueError(f"unsupported CBOR major type {major}")


def smp_decode(raw):
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
    body = framed[2:-2]
    if len(framed) < 4 or crc16_xmodem(body) != struct.unpack(">H", framed[-2:])[0]:
        raise ValueError("SMP CRC mismatch")
    if len(body) < 8:
        raise ValueError("SMP body too short")
    value, _ = cbor_decode(body[8:])
    return value if isinstance(value, dict) else {"value": value}


def smp_talk(port, frame, timeout=2.0):
    """One SMP request on a fresh handle, with the open-retry Windows needs."""
    last = None
    for _ in range(4):
        try:
            with open_port(port, 0.05):
                pass
            break
        except serial.SerialException as e:
            last = e
            time.sleep(0.35)
    else:
        raise last
    with open_port(port) as ser:
        ser.dtr = True
        ser.rts = True
        ser.timeout = 0.02
        for _ in range(3):
            if not ser.read(256):
                break
        time.sleep(SETTLE_AFTER_OPEN)
        ser.write(frame)
        ser.flush()
        raw, deadline = b"", time.monotonic() + timeout
        while time.monotonic() < deadline:
            n = ser.in_waiting
            if n:
                raw += ser.read(n)
                time.sleep(RESPONSE_GRACE)
                if not ser.in_waiting:
                    break
            else:
                time.sleep(0.005)
    if not raw:
        raise TimeoutError("no SMP response")
    return smp_decode(raw), raw


def jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [jsonable(x) for x in v]
    return v


def describe_slots(state):
    rows = []
    for img in state.get("images") or []:
        h = img.get("hash")
        h = h.hex() if isinstance(h, (bytes, bytearray)) else (str(h) if h else "")
        flags = [k for k in ("active", "confirmed", "pending", "permanent", "bootable")
                 if img.get(k)]
        rows.append({"slot": img.get("slot"), "version": img.get("version"), "hash": h,
                     "known_as": KNOWN_IMAGES.get(h.lower(), "not a Naya image we know" if h else "no image"),
                     "flags": flags})
    return rows


def watch_console(port, seconds):
    """Read whatever the bootloader's console port says for `seconds`. MCUboot prints its
    boot log only as it boots, so unplug/replug the half while this listens."""
    text = b""
    try:
        with open_port(port, 0.2) as ser:
            ser.dtr = True
            ser.rts = True
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    text += chunk
    except serial.SerialException as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"bytes": len(text), "text": text.decode("utf-8", "replace")}


def naya_ports(side=None, mode=None):
    out = []
    for p in comports():
        info = pid_info(p.pid) if p.vid == NAYA_VID else None
        if info and (side is None or info["side"] == side) and (mode is None or info["mode"] == mode):
            out.append((p, info))
    return out


def enter_bootloader(side):
    """--bootloader: restart one half into MCUboot, as OpenFlow's firmware procedure does before
    an upload, and wait for its bootloader ports. Writes nothing to the half's flash."""
    app = naya_ports(side, "app")
    if not app:
        return {"entered": False, "why": f"no {side} half running its application on USB"}
    port = app[0][0].device
    print(f"\nRestarting the {side} half ({port}) into its bootloader. Its lights go off; that is "
          "expected, and it is brought back at the end.")
    try:
        with open_port(port) as ser:
            ser.dtr = True
            ser.rts = True
            cdc_handshake(ser, DEST[side])
            ser.write(cdc_build(DEST[side], CAT_RESET, RESET_MCU_BOOT))
            ser.flush()
    except serial.SerialException:
        pass                                          # it reboots mid-reply
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if naya_ports(side, "mcuboot"):
            time.sleep(1.0)                           # let the second CDC port enumerate too
            return {"entered": True, "from_port": port}
        time.sleep(0.5)
    return {"entered": False, "from_port": port,
            "why": "the bootloader did not appear on USB within 45 s"}


def leave_bootloader(report, side):
    """Send `os reset` to the half's bootloader so it boots its application again."""
    entry = next((b for b in report["bootloaders"] if b["side"] == side and b.get("smp_port")), None)
    ports = [entry["smp_port"]] if entry else [p.device for p, _ in naya_ports(side, "mcuboot")]
    for port in ports:
        try:
            smp_talk(port, smp_request(SMP_OP_WRITE, SMP_GROUP_OS, SMP_ID_OS_RESET), timeout=2.0)
        except Exception:                             # noqa: BLE001 -- the reset drops the port
            pass
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if naya_ports(side, "app"):
            return {"back_in_application": True}
        time.sleep(1.0)
    return {"back_in_application": False,
            "why": "not back in its application after 60 s: unplug and replug that half"}


# ------------------------------------------------------------------------------------------- #
def probe(watch_log=0.0, bootloader_side=None):
    report = {"at": datetime.now().isoformat(timespec="seconds"), "python": sys.version.split()[0],
              "platform": sys.platform, "ports": [], "halves": [], "bootloaders": [], "notes": []}
    if bootloader_side:
        report["enter_bootloader"] = enter_bootloader(bootloader_side)
        print(f"  {report['enter_bootloader']}")
        watch_log = max(watch_log, 10.0)

    ports = list(comports())
    print(f"\n{len(ports)} serial port(s) on this machine")
    naya = []
    for p in sorted(ports, key=lambda x: x.device):
        info = pid_info(p.pid) if p.vid == NAYA_VID else None
        row = {"port": p.device, "vid": p.vid, "pid": p.pid, "serial": p.serial_number,
               "description": p.description, "naya": info}
        report["ports"].append(row)
        tag = (f"NAYA {info['side']} {info['mode']} gen {info['generation']}" if info
               else ("NAYA (pid not in the known table)" if p.vid == NAYA_VID else ""))
        vid = f"{p.vid:04X}" if p.vid is not None else "----"
        pid = f"{p.pid:04X}" if p.pid is not None else "----"
        print(f"  {p.device:8} VID={vid} PID={pid} serial={p.serial_number or '-':18} {tag}")
        if p.vid == NAYA_VID:
            naya.append((p, info))
    if not naya:
        print("\n  No Naya device is enumerating at all. Try another cable or port, and note "
              "whether the halves' lights come on.")
        report["notes"].append("no Naya VID on any port")

    # --- application halves -------------------------------------------------------------- #
    for p, info in naya:
        if not info or info["mode"] != "app":
            continue
        side = info["side"]
        print(f"\n{side.upper()} half on {p.device} (application, generation {info['generation']})")
        half = {"port": p.device, "side": side, "generation": info["generation"],
                "serial": p.serial_number, "reads": {}}
        try:
            with open_port(p.device) as ser:
                ser.dtr = True
                ser.rts = True
                time.sleep(0.1)
                ser.read(4096)
                if not cdc_handshake(ser, DEST[side]):
                    half["error"] = "no handshake: the port is there but the application did not answer"
                    print(f"  {half['error']}")
                else:
                    own = app_reads(ser, DEST[side])
                    half["reads"]["self"] = own
                    print(f"  firmware   {own['firmwareVersion'] or '(no answer)'}")
                    print(f"  own addr   {own['bleAddress']}")
                    print(f"  pair addr  {own['pairAddress']}")
                    print(f"  bond table {own['allPairs']}")
                    # The PARTNER through this port. If the other half's own USB is dead but it
                    # is linked, this is where it shows up.
                    other = "right" if side == "left" else "left"
                    via = app_reads(ser, DEST[other])
                    half["reads"]["partner_via_this_port"] = via
                    # Only the central (left) half routes commands to its partner, and only the
                    # version travels over the link; the Bluetooth reads answer for the half you
                    # are plugged into, so they are not shown here.
                    if via["firmwareVersion"]:
                        print(f"  partner ({other}) reached THROUGH this port: firmware "
                              f"{via['firmwareVersion']} -- the {other} half is alive and linked")
                    elif side == "left":
                        print(f"  partner ({other}) through this port: no answer -- the {other} half "
                              "is not linked to this one right now")
                    else:
                        print(f"  partner ({other}) through this port: not reachable this way "
                              "(only the left half routes to its partner)")
        except serial.SerialException as e:
            half["error"] = f"could not open: {e}"
            print(f"  could not open {p.device}: {e}")
            if "denied" in str(e).lower() or "busy" in str(e).lower():
                print("  -> another program holds this port. Close NayaFlow / OpenFlow and run again.")
        report["halves"].append(half)

    # --- halves in the bootloader ------------------------------------------------------- #
    boot = [(p, info) for p, info in naya if info and info["mode"] == "mcuboot"]
    by_serial = {}
    for p, info in boot:
        by_serial.setdefault(p.serial_number or p.device, []).append((p, info))
    for key, group in by_serial.items():
        info = group[0][1]
        ports_here = [p.device for p, _ in group]
        print(f"\n{info['side'].upper()} half in the MCUboot BOOTLOADER, generation {info['generation']}, "
              f"ports {ports_here} (serial {key})")
        print("  (this half is not running its firmware; the bootloader is waiting for an upload)")
        entry = {"side": info["side"], "generation": info["generation"], "serial": key,
                 "ports": ports_here, "smp_port": None, "log_port": None, "slots": None,
                 "slot_info": None, "raw": {}, "console": None}
        # Find the port that speaks SMP. Right after enumeration the first reads can fail for
        # a while; that is the bootloader not answering yet, not the bootloader gone.
        state = None
        deadline = time.monotonic() + 45.0
        attempt = 0
        while state is None and time.monotonic() < deadline:
            attempt += 1
            for port in ports_here:
                try:
                    state, raw = smp_talk(port, smp_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE))
                    entry["smp_port"] = port
                    entry["raw"]["image_state"] = raw.decode("ascii", "replace")
                    break
                except Exception as e:                # noqa: BLE001 -- the log port, or not yet
                    entry["raw"].setdefault("attempts", []).append(f"{port}: {type(e).__name__}: {e}")
            if state is None:
                time.sleep(2.0)
        if state is None:
            entry["error"] = "neither port answered SMP in 45 s"
            print(f"  {entry['error']} -- if OpenFlow/NayaFlow is open, close it and run again")
        else:
            entry["log_port"] = next((x for x in ports_here if x != entry["smp_port"]), None)
            print(f"  SMP answers on {entry['smp_port']} (after {attempt} attempt(s)); "
                  f"console is {entry['log_port']}")
            slots = describe_slots(state)
            entry["slots"] = slots
            entry["raw"]["image_state_decoded"] = jsonable(state)
            if not slots:
                print("  image state: NO images reported -- both slots empty or invalid")
            for s in slots:
                print(f"  slot {s['slot']}: {s['known_as']:28} flags={s['flags'] or '-'}  "
                      f"version={s['version']}  hash={s['hash'][:16] or '-'}...")
            if state.get("rc"):
                print(f"  image state rc={state.get('rc')}")
            try:
                si, raw = smp_talk(entry["smp_port"], smp_request(SMP_OP_READ, SMP_GROUP_IMAGE, SMP_ID_IMAGE_SLOT_INFO))
                entry["raw"]["slot_info"] = raw.decode("ascii", "replace")
                if si.get("rc") == SMP_ERR_ENOTSUP:
                    entry["slot_info"] = {"supported": False}
                    print("  slot info: not supported by this bootloader (normal)")
                else:
                    entry["slot_info"] = jsonable(si)
                    print(f"  slot info: {json.dumps(jsonable(si))[:200]}")
            except Exception as e:                    # noqa: BLE001
                entry["slot_info"] = {"error": f"{type(e).__name__}: {e}"}
                print(f"  slot info: no answer ({type(e).__name__})")
            if entry["log_port"]:
                secs = watch_log if watch_log > 0 else 2.0
                if watch_log > 0:
                    print(f"  listening to the console on {entry['log_port']} for {secs:.0f} s -- "
                          "unplug and replug this half NOW to capture its boot messages")
                entry["console"] = watch_console(entry["log_port"], secs)
                txt = (entry["console"] or {}).get("text", "")
                if txt.strip():
                    print("  console said:")
                    for line in txt.strip().splitlines()[-25:]:
                        print(f"    | {line}")
                else:
                    print(f"  console: nothing in {secs:.0f} s (MCUboot only prints as it boots; "
                          "rerun with --watch-log 20 and replug the half while it listens)")
        report["bootloaders"].append(entry)

    if bootloader_side and (report["enter_bootloader"].get("entered")
                            or naya_ports(bootloader_side, "mcuboot")):
        print(f"\nBringing the {bootloader_side} half back into its application ...")
        report["leave_bootloader"] = leave_bootloader(report, bootloader_side)
        print(f"  {report['leave_bootloader']}")

    out = Path(__file__).with_name(f"naya-probe-{datetime.now():%Y%m%d-%H%M%S}.json")
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nSaved {out}\nSend that file back. Nothing was written to the keyboard's flash.")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Read-only probe of a Naya Create over USB.")
    ap.add_argument("--watch-log", type=float, default=0.0, metavar="SECONDS",
                    help="listen to a bootloader half's console this long (replug it meanwhile)")
    ap.add_argument("--bootloader", choices=("left", "right"),
                    help="restart this half into its bootloader, read both flash slots, and "
                         "restart it back into its application (writes nothing to flash)")
    args = ap.parse_args()
    try:
        probe(args.watch_log, args.bootloader)
    except KeyboardInterrupt:
        print("\nstopped")
