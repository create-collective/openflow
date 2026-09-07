"""DeviceService — structured, thread-safe access to the Naya Create over USB CDC.

This is the piece the plan calls out as "work still to be done on nayactl": the
useful business logic (status aggregation, battery math, module detection) lives
in nayactl's CLI layer and prints via click.echo. Here it is lifted into library
functions that return plain dicts, so the API layer and (eventually) a nayactl
pull request can share it.

Serial I/O is blocking, so every device call goes through a single lock. Callers
from async code must use asyncio.to_thread / run_in_threadpool.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .._vendor.nayactl import constants as C
from .._vendor.nayactl.discovery import find_naya_serial_ports
from .._vendor.nayactl.transport import (
    DangerousCommandError,
    SerialTransport,
    TransportError,
)
from .._vendor.nayactl.util import format_fw_version, hexline

__all__ = [
    "DeviceService",
    "TransportError",
    "DangerousCommandError",
    "parse_keyscan_event",
]


def parse_keyscan_event(frame_payload: bytes) -> dict | None:
    """Decode a KEYSCAN_EVENT payload ([row, col, state])."""
    if len(frame_payload) < 3:
        return None
    row, col, state = frame_payload[0], frame_payload[1], frame_payload[2]
    return {"row": row, "col": col, "pressed": state == 0}


def _first_payload(responses) -> bytes | None:
    for r in responses:
        if getattr(r, "valid", False):
            return r.payload
    return None


# Cell voltages arrive in TWO different units, and mixing them up is exactly what went wrong:
# SYS_GET_KB_BATTERY_LEVEL reports millivolts (4152 = 4.152 V), while MODULE_GET_BATTERY reports
# tenths of a millivolt (41520). MODULE_GET_PRECISE_BATTERY reports plain MILLIVOLTS despite the
# name, and its value used to be fed straight into the 0.1 mV maths -- which clamped every module
# to the 3.3 V floor, so a fully charged module read as 1%.
#
# Confirmed on module firmware 2.3.3 by sending both commands back to back to the same module:
#     Track   PRECISE 0x1038 = 4152 mV     GET_BATTERY 0xA1CF = 41423 (0.1 mV)
#     Tune    PRECISE 0x108C = 4236 mV     GET_BATTERY 0xA64C = 42572 (0.1 mV)
#
# The unit is SNIFFED rather than blindly scaled: no real cell reads below 1.0 V, so anything
# under 10000 is unambiguously millivolts. That keeps this correct either way if some module
# firmware turns out to report the precise value in 0.1 mV after all.
_MILLIVOLT_LIMIT = 10000


def _to_millivolts(raw: int) -> int:
    """Any reported cell voltage -> millivolts, whichever unit the command answered in."""
    return raw if 0 < raw < _MILLIVOLT_LIMIT else raw // 10


def _battery_percent(millivolts: int) -> int:
    """Map a cell voltage in mV onto 1-100% across the 3.3 V - 4.2 V window.

    One helper for both the keyboard and its modules; they were separate copies of the same
    curve written at different scales, which is how the units drifted apart.
    """
    clamped = max(3300, min(4200, millivolts))
    return max(1, min(100, ((clamped - 3300) * 100) // 900))


def pairing_report(halves: list[dict]) -> dict:
    """Are the two halves actually bonded to each other? Pure; takes a verbose status list.

    This exists to separate two failures that look identical to a user -- "my right half stopped
    working" is either a half that is not powered/enumerating at all, or two halves that are fine
    but no longer bonded. NayaFlow cannot tell you which: a half that does not enumerate simply
    never appears in its update list, and it ships no per-half recovery.

    The check is a cross-comparison, not a flag we are trusting the device to set: each half
    reports its own BLE address and the address it is paired TO, so a healthy pair is exactly
    `left.pairAddress == right.bleAddress` and `right.pairAddress == left.bleAddress`. Verified
    on a working pair 2026-09-07.

    A one-directional match is called out separately rather than being rounded to "paired" or
    "not paired", because it is a real state (one half re-paired, the other still pointing at an
    old partner) and rounding it either way would send someone down the wrong repair path.
    """
    by_side = {h.get("side"): h for h in halves if h.get("connected")}
    left, right = by_side.get("left"), by_side.get("right")
    if left is None or right is None:
        present = sorted(by_side)
        return {"state": "incomplete",
                "detail": f"only {', '.join(present) or 'no halves'} connected over USB; "
                          "a pairing check needs both halves."}

    def addr(h):
        return (h.get("bleAddress") or "").upper()

    def paired_to(h):
        return ((h.get("ble") or {}).get("pairAddress") or "").upper()

    l_ok = paired_to(left) and paired_to(left) == addr(right)
    r_ok = paired_to(right) and paired_to(right) == addr(left)
    if not paired_to(left) and not paired_to(right):
        return {"state": "unknown", "detail": "neither half reported a pair address."}
    if l_ok and r_ok:
        return {"state": "paired",
                "detail": f"each half is bonded to the other ({addr(left)} <-> {addr(right)})."}
    if l_ok or r_ok:
        one = "left" if l_ok else "right"
        return {"state": "half-paired",
                "detail": f"only the {one} half points at its partner. The other is still bonded "
                          f"to a different address, so the split link will not come up."}
    return {"state": "not-paired",
            "detail": f"neither half points at the other. Left is bonded to "
                      f"{paired_to(left) or 'nothing'}, right to {paired_to(right) or 'nothing'}."}


class DeviceService:
    """Owns serial connections to connected halves and exposes structured ops."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._transports: dict[str, SerialTransport] = {}

    # --- connection management -------------------------------------------------

    def _dest_for_side(self, side: str) -> int:
        return C.SIDE_DEST.get(side, C.DEST_LEFT)

    def _transport_for(self, port: str, dest: int) -> SerialTransport:
        t = self._transports.get(port)
        if t is not None and t.is_connected:
            return t
        # (Re)connect.
        if t is not None:
            try:
                t.disconnect()
            except Exception:
                pass
        t = SerialTransport(port, dest)
        t.connect()  # performs the mandatory CDC handshake
        self._transports[port] = t
        return t

    def _drop(self, port: str) -> None:
        t = self._transports.pop(port, None)
        if t is not None:
            try:
                t.disconnect()
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._lock:
            for port in list(self._transports):
                self._drop(port)

    # --- discovery -------------------------------------------------------------

    def list_devices(self) -> list[dict]:
        """Enumerate connected Naya devices by USB VID/PID (no serial I/O)."""
        return [
            {
                "port": d.port,
                "pid": d.pid,
                "side": d.side,
                "description": d.description,
                "serialNumber": d.serial_number,
            }
            for d in find_naya_serial_ports()
        ]

    # --- status ----------------------------------------------------------------

    def status_all(self, verbose: bool = False) -> list[dict]:
        """Query every connected half + module. Structured mirror of nayactl status.

        `verbose` adds the BLE identity block, which costs five more round trips per half.
        It used to be accepted and then ignored -- the Information page needs it, the Device
        Manager's refresh does not, so it is honoured now rather than dropped.
        """
        out: list[dict] = []
        with self._lock:
            for dev in find_naya_serial_ports():
                entry: dict = {
                    "port": dev.port,
                    "side": dev.side,
                    "description": dev.description,
                    # The USB product id. Carried because it is the half's identity to the
                    # host -- it is what distinguishes left (0x0064) from right (0x00C8), and
                    # what a firmware image must be selected by (the two flash generations are
                    # not interchangeable; see docs/firmware-analysis.md).
                    "pid": getattr(dev, "pid", None),
                    "serialNumber": getattr(dev, "serial_number", None),
                    "connected": False,
                }
                try:
                    dest = self._dest_for_side(dev.side)
                    t = self._transport_for(dev.port, dest)
                    entry.update(self._query_half(t, dest, deep=verbose))
                    entry["connected"] = True
                except TransportError as e:
                    entry["error"] = str(e)
                    self._drop(dev.port)
                out.append(entry)
        return out

    def _query_half(self, t: SerialTransport, dest: int, deep: bool = False) -> dict:
        info: dict = {}

        payload = _first_payload(t.send_command(dest, C.CAT_SYSTEM, C.SYS_GET_FW_VERSION))
        if payload is not None:
            info["firmwareVersion"] = format_fw_version(payload)

        payload = _first_payload(t.send_command(dest, C.CAT_SYSTEM, C.SYS_GET_HW_ID_NUMBER))
        if payload is not None:
            try:
                info["hardwareId"] = payload.decode("ascii")
            except (UnicodeDecodeError, ValueError):
                info["hardwareId"] = hexline(payload)

        volts: list[int] = []
        for _ in range(5):
            p = _first_payload(
                t.send_command(dest, C.CAT_SYSTEM, C.SYS_GET_KB_BATTERY_LEVEL, timeout=0.5)
            )
            if p is not None and len(p) >= 2:
                volts.append((p[0] << 8) | p[1])
        if volts:
            volts.sort()
            mv = _to_millivolts(volts[len(volts) // 2])
            info["batteryPercent"] = _battery_percent(mv)
            info["batteryMillivolts"] = mv

        payload = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_ADDRESS))
        if payload is not None and len(payload) >= 6:
            info["bleAddress"] = ":".join(f"{b:02X}" for b in payload[:6])

        # BLE identity, only when asked. Every one of these commands already existed in
        # constants.py and nothing called them, so a half's name, its paired partner and its
        # radio firmware were all unreachable from the app despite being one read away.
        #
        # Decoded conservatively: a name is ASCII, an address is six bytes, a version goes
        # through format_fw_version. BLE_GET_STATUS is reported as raw hex because we have no
        # capture telling us what its bytes mean, and inventing a reading for them is how this
        # project has been wrong before.
        if deep:
            ble: dict = {}
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_NAME))
            if p is not None:
                try:
                    ble["name"] = p.decode("ascii").rstrip("\x00").strip()
                except (UnicodeDecodeError, ValueError):
                    ble["name"] = hexline(p)
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_PAIR_ADDRESS))
            if p is not None and len(p) >= 6:
                ble["pairAddress"] = ":".join(f"{b:02X}" for b in p[:6])
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_DONGLE_ADDR))
            if p is not None and len(p) >= 6:
                ble["dongleAddress"] = ":".join(f"{b:02X}" for b in p[:6])
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_FW_VERSION))
            if p is not None:
                ble["firmwareVersion"] = format_fw_version(p)
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_STATUS))
            if p is not None:
                ble["statusRaw"] = p.hex()
            if ble:
                info["ble"] = ble

        # Module detection. Type is DERIVED FROM THE ADDRESS, not from MODULE_DETECT (which
        # only reports presence = 0x01 for every module — keying the type on it mislabels
        # every docked module "Touch"). The address comes from the handshake ([01][addr]) or
        # GET_ADDRESS. See docs/remap-protocol-live.md.
        handshake = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_SEND_HANDSHAKE, timeout=1.5))
        payload = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_DETECT))
        if payload is not None and len(payload) >= 1 and payload[0] != 0:
            addr = handshake[1] if handshake is not None and len(handshake) >= 2 else None
            if addr is None:
                ap = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_ADDRESS))
                addr = ap[0] if ap is not None and len(ap) >= 1 else None
            module: dict = {"type": C.module_type_from_address(addr)}
            if addr is not None:
                module["address"] = addr
                # The address's low bit is the side, so the board tells us which half a
                # module is docked on -- no guessing from which port answered.
                module["docked"] = C.module_side_from_address(addr)
            mp = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_FW_VERSION))
            if mp is not None:
                module["firmwareVersion"] = format_fw_version(mp)
            mp = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_PRECISE_BATTERY))
            if mp is not None and len(mp) >= 2:
                voltage = (mp[0] << 8) | mp[1]
                valid = (mp[2] == 0) if len(mp) >= 3 else True
                if valid and voltage > 0:
                    mv = _to_millivolts(voltage)
                    module["voltage"] = voltage          # raw, exactly as the device reported it
                    module["batteryMillivolts"] = mv
                    module["batteryPercent"] = _battery_percent(mv)
            info["module"] = module

        return info

    # --- LED -------------------------------------------------------------------

    _LED_ACTIONS = {
        "on": C.LED_ON,
        "off": C.LED_OFF,
        "toggle": C.LED_TOGGLE,
        "halt": C.LED_HALT,
        "resume": C.LED_RESUME,
    }

    def led(self, side: str, action: str, value: int | None = None) -> dict:
        with self._lock:
            dev = self._require_side(side)
            dest = self._dest_for_side(dev.side)
            t = self._transport_for(dev.port, dest)
            if action == "brightness":
                if value is None:
                    raise ValueError("brightness requires a value 0-255")
                t.send_command(dest, C.CAT_LED, C.LED_ADJUST_BRIGHTNESS, bytes([value & 0xFF]))
            elif action == "effect":
                if value is None:
                    raise ValueError("effect requires an index")
                t.send_command(dest, C.CAT_LED, C.LED_SELECT_EFFECT, bytes([value & 0xFF]))
            elif action in self._LED_ACTIONS:
                t.send_command(dest, C.CAT_LED, self._LED_ACTIONS[action])
            else:
                raise ValueError(f"unknown LED action: {action}")
            return {"ok": True, "side": dev.side, "action": action, "value": value}

    # --- text protocol ---------------------------------------------------------

    def text_command(self, side: str, command: str, force: bool = False) -> dict:
        with self._lock:
            dev = self._require_side(side)
            dest = self._dest_for_side(dev.side)
            t = self._transport_for(dev.port, dest)
            reply = t.send_text(command, allow_dangerous=force)
            return {"ok": True, "side": dev.side, "command": command, "reply": reply}

    def dump_settings(self, side: str) -> dict:
        return self.text_command(side, "dump_settings")

    # --- keymap read (REMAP) ---------------------------------------------------

    def read_keymap(self, side: str = "left") -> dict:
        """Read the full board keymap (bindings + LED colours) off a connected half.

        The central/left half holds the whole-board map, so default to it. Returns
        the raw read for db.keymap_import to translate + persist. Read-only."""
        from . import keymap_read

        with self._lock:
            dev = self._require_side(side)
            dest = self._dest_for_side(dev.side)
            t = self._transport_for(dev.port, dest)
            return keymap_read.read_keymap(t, dest)

    def read_module_configs(self, side: str = "left") -> dict:
        """Read the module config list + every non-empty slot. Read-only.

        Module configs live on the central/left half regardless of which half a module is
        docked to (checked: the right half reports no slots at all), so this defaults to left
        like read_keymap. Returns {"list": hex, "slots": {slot: [{field, type, value}]}} plus
        {"by_uuid": {module_config_id: slot}} -- always resolve a slot through that map rather
        than assuming an index, because slots move between flashes.
        """
        from . import keymap_read
        from . import flash as F

        with self._lock:
            dev = self._require_side(side)
            dest = self._dest_for_side(dev.side)
            t = self._transport_for(dev.port, dest)
            read = keymap_read.read_module_configs(t, dest)
        return {
            "list": read["list"].hex(),
            "by_uuid": F.slot_map_for(read["list"]),
            "slots": {slot: [{"field": f, "type": ty, "value": v.hex()} for f, ty, v in recs]
                      for slot, recs in read["slots"].items()},
        }

    # --- troubleshooting -------------------------------------------------------

    def spi_flash_test(self, side: str) -> dict:
        """Read-only SPI flash self-test (0xFA/0x1001). Does NOT format/erase."""
        with self._lock:
            dev = self._require_side(side)
            dest = self._dest_for_side(dev.side)
            t = self._transport_for(dev.port, dest)
            responses = t.send_command(dest, C.CAT_FLASH, C.FLASH_TEST, timeout=3.0)
            payload = _first_payload(responses)
            return {
                "ok": payload is not None,
                "side": dev.side,
                "raw": payload.hex() if payload else "",
            }

    def clear_ble_devices(self, side: str, force: bool = False) -> dict:
        """Clear BLE bonds (text: clear_bonds). Destructive: requires force."""
        return self.text_command(side, "clear_bonds", force=force)

    # --- keyscan (blocking; run on a worker thread) ----------------------------

    def keyscan(self, side: str, duration: float, callback: Callable[[dict], None]) -> None:
        """Toggle keyscan mode on, stream events for `duration`s, then toggle off."""
        with self._lock:
            dev = self._require_side(side)
            dest = self._dest_for_side(dev.side)
            t = self._transport_for(dev.port, dest)
            t.send_command(dest, C.CAT_SYSTEM, C.SYS_TOGGLE_KEYSCAN_MODE, b"\x01")
            try:
                def on_frame(frame: bytes) -> None:
                    # Frame layout: header(6) + subcmd(2) + flags(1) + payload + xor + EOT
                    if len(frame) < 11:
                        return
                    category = frame[4]
                    subcmd = (frame[6] << 8) | frame[7]
                    if category == C.CAT_SYSTEM and subcmd == C.SYS_KEYSCAN_EVENT:
                        data_size = frame[5]
                        payload = frame[9 : 6 + data_size]
                        ev = parse_keyscan_event(payload)
                        if ev is not None:
                            callback(ev)

                t.listen(duration, on_frame)
            finally:
                t.send_command(dest, C.CAT_SYSTEM, C.SYS_TOGGLE_KEYSCAN_MODE, b"\x00")

    # --- helpers ---------------------------------------------------------------

    def _require_side(self, side: str):
        for d in find_naya_serial_ports():
            if d.side == side:
                return d
        # fall back to first device if the exact side isn't present
        devs = find_naya_serial_ports()
        if devs:
            return devs[0]
        raise TransportError(f"No {side} device found. Is it connected via USB?")
