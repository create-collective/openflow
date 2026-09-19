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

import json
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
from . import ble_status, port_access, spi_flash_test

__all__ = [
    "DeviceService",
    "TransportError",
    "DangerousCommandError",
    "parse_keyscan_event",
]


# Ports the user has told us to leave alone, kept in the data directory rather than in
# memory: the ghosts this exists for survive an app restart, so an ignore that did not
# would be no use.
IGNORED_PORTS_FILE = "ignored-ports.json"


def _ignored_path():
    from ..config import data_dir
    return data_dir() / IGNORED_PORTS_FILE


def _load_ignored() -> set:
    try:
        got = json.loads(_ignored_path().read_text(encoding="utf-8"))
        return {str(p) for p in got} if isinstance(got, list) else set()
    except Exception:
        return set()          # missing or malformed: ignore nothing, never fail to start


def _save_ignored(ports: set) -> None:
    try:
        path = _ignored_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(ports)), encoding="utf-8")
    except OSError:
        pass                  # a read-only data dir must not break the app


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


def _link_views(halves: list[dict]) -> dict:
    """side -> split-link quality, from the decoded BLE status blob.

    This is the LINK, where the verdict below is the BOND: two halves can be correctly bonded and
    still have a link that is dropping, and until now we reported only the first. See
    device/ble_status.py.

    The expectation passed in is the PARTNER's own `bleAddress`, which comes from a different
    command than the status blob -- so this stays a genuine cross-check rather than the device
    agreeing with itself. It falls back to this half's own `pairAddress` when the partner did not
    answer, which is weaker but still catches a link pointing at nothing.
    """
    out: dict = {}
    for h in halves:
        side = h.get("side")
        ble = h.get("ble") or {}
        decoded = ble.get("status")
        if not side or not decoded:
            continue
        partner = next((x for x in halves if x.get("side") and x.get("side") != side), None)
        expected = (partner or {}).get("bleAddress") or ble.get("pairAddress")
        out[side] = ble_status.link_summary(decoded, expected)
    return out


def pairing_report(halves: list[dict]) -> dict:
    """Bond verdict plus, where the device told us, per-half link quality."""
    report = _pairing_verdict(halves)
    links = _link_views(halves)
    if links:
        report["links"] = links
    return report


def _pairing_verdict(halves: list[dict]) -> dict:
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


# The order two halves are drawn in, everywhere. A keyboard has a left and a right and the
# screen has a left and a right; matching them is the whole of it. Anything unexpected (a
# dongle, an unknown side) sorts after, rather than being dropped or silently leading.
_SIDE_ORDER = {"left": 0, "right": 1}


class DeviceService:
    """Owns serial connections to connected halves and exposes structured ops."""

    RELEASED_REASON = "released so other software can use the keyboard"
    RELEASED_ERROR = ("the keyboard is released so other software can use it; "
                      "reconnect in OpenFlow to take it back")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._transports: dict[str, SerialTransport] = {}
        # Released: every port closed and the poll standing down, so another application can
        # talk to the keyboard. Not a connection state of the device -- a decision of ours.
        self._released = False
        # Live status (see tick): side -> the last tick's snapshot; port -> identity read once;
        # battery samples folded across ticks, keyed "side" and "side:module".
        self._live: dict[str, dict] = {}
        self._identity: dict[str, dict] = {}
        # A docked module's firmware, read once per docking (side, address); it cannot change
        # while docked, and the poll should not spend a round trip on it every tick.
        self._module_fw: dict = {}
        # Which battery command each docked module answers: 'precise' or 'legacy'. Probed
        # once per docking; see _module_voltage. Keyed like _module_fw.
        self._module_batt: dict = {}
        self._samples: dict[str, list] = {}
        # port -> {"ok": bool, "at": float}: did this port last answer a handshake? Windows
        # keeps enumerating a port whose device detached uncleanly, and such a ghost is
        # indistinguishable from a live one until something tries to talk to it.
        self._port_health: dict[str, dict] = {}
        # Ports the user has told us to leave alone. Persisted: the ghosts that prompted
        # this survived an app restart, so an ignore that did not would be useless.
        self._ignored: set[str] = _load_ignored()

    # --- connection management -------------------------------------------------

    def _dest_for_side(self, side: str) -> int:
        return C.SIDE_DEST.get(side, C.DEST_LEFT)

    # A cached transport can be dead without knowing it. After the board power-cycles, pyserial
    # still reports the port open, but the handle belongs to a device instance Windows has already
    # torn down, and the first write fails with "WriteFile failed (PermissionError(13, 'The device
    # does not recognize the command.'))". Discovery drops such a transport on error; the RPC
    # paths did not, so after a power cycle every LED / read / flash call failed until the backend
    # was restarted (seen 2026-09-10, board power-cycled during a test with the app open).
    # Two defences: a cheap liveness check on the cached handle before it is handed out, and one
    # retry on a fresh handle when a write fails before anything was sent.
    _DEAD_HANDLE = ("Write to ", "Serial port not open")

    @staticmethod
    def _alive(t) -> bool:
        """False when the underlying serial handle rejects even a status query."""
        ser = getattr(t, "_ser", None)
        if ser is None:
            return True            # not a real serial transport (tests); trust is_connected
        try:
            ser.in_waiting
            return True
        except Exception:
            return False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> dict:
        """Hand the keyboard over: close every handle and stop the poll reopening them.

        The halves are marked not connected, because after this we genuinely do not know what
        they are doing -- another application may be flashing them. The reason says it was a
        choice rather than a cable falling out."""
        with self._lock:
            self._released = True
            for port in list(self._transports):
                self._drop(port)
            for side, snap in list(self._live.items()):
                if snap.get("connected"):
                    self._mark_disconnected(side, snap.get("port"), self.RELEASED_REASON)
        return {"released": True}

    def reconnect(self) -> dict:
        """Take it back. The next poll tick reopens whatever is still on the bus."""
        with self._lock:
            self._released = False
        return {"released": False}

    def _transport_for(self, port: str, dest: int) -> SerialTransport:
        # The CACHE holds the real transport; the caller gets it wrapped in a LoggingTransport so
        # every send is recorded (device_log). Wrapping on return, not in the cache, keeps the
        # cached identity and the liveness check operating on the real handle.
        from .device_log import LoggingTransport
        if self._released:
            raise TransportError(self.RELEASED_ERROR)
        t = self._transports.get(port)
        if not (t is not None and t.is_connected and self._alive(t)):
            if t is not None:
                try:
                    t.disconnect()
                except Exception:
                    pass
            t = SerialTransport(port, dest)
            # The one place a port is proved good or bad, so what we remember about it cannot
            # drift from what happened when something actually tried to talk to it.
            try:
                t.connect()  # performs the mandatory CDC handshake
            except TransportError as e:
                self._note_port(port, False)
                # Linux without the udev rule: say so, with the fix, instead of "Cannot open".
                if port_access.is_permission_denied(e):
                    raise port_access.PortAccessDenied(port) from e
                raise
            except Exception:
                self._note_port(port, False)
                raise
            self._note_port(port, True)
            self._transports[port] = t
        return LoggingTransport(t, port)

    def _drop(self, port: str) -> None:
        t = self._transports.pop(port, None)
        if t is not None:
            try:
                t.disconnect()
            except Exception:
                pass

    def _with_transport(self, side: str, fn):
        """Run fn(transport, dest, dev) under the lock; once more on a fresh handle if the cached
        one turns out to be dead. Only a failure that means NOTHING WAS SENT is retried (a write
        that failed at the driver, or a port that is not open). A timeout is not: the command may
        have landed, and re-sending it is the caller's decision."""
        with self._lock:
            dev, t = self._connect_side(side)
            dest = self._dest_for_side(dev.side)
            try:
                return fn(t, dest, dev)
            except TransportError as e:
                if not str(e).startswith(self._DEAD_HANDLE):
                    raise
                self._drop(dev.port)
                t = self._transport_for(dev.port, dest)   # raises "Cannot open" if it is gone
                return fn(t, dest, dev)

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
            for d, _others in self.halves_seen()
        ]

    # --- live status: one light tick per half, on the app's timer -----------------------------
    # The keyboard never pushes battery on its own. NayaFlow's bar looks live because NayaCore
    # holds each half's port and polls it on a 6 s tick (its DETECT_MODULE job; the failed ticks
    # in its log land six seconds apart). This is the same thing, done here: keyboard battery,
    # module presence and module battery, one sample each per tick, under the service lock so a
    # tick waits behind a flash rather than interleaving with it. Identity -- firmware, hardware
    # id, radio address -- never changes while plugged in, so it is read once per port and kept.
    # The full status read (status_all) stays as it is for the Information page.
    TICK_SAMPLES = 5          # ticks folded into the reported battery; nayactl samples 5 per read

    # The two ways a module reports its cell voltage. PRECISE answers in millivolts and is
    # absent on older module firmware (2.1.2 measured: no payload, 1.09 s of timeout every
    # time it is asked). LEGACY answers in 0.1 mV and is present on both. _to_millivolts
    # sniffs the unit by magnitude, so either lands correctly without a version check.
    #
    # Payload shapes differ and neither is guessed: PRECISE is [voltage hi][lo][status],
    # status 0 meaning valid; LEGACY is [_][batt hi][batt lo][usb hi][usb lo]. Both are the
    # decodes nayactl uses (cli/status.py), which were measured against real modules.
    @staticmethod
    def _decode_precise(p) -> int | None:
        if p is None or len(p) < 2:
            return None
        if len(p) >= 3 and p[2] != 0:
            return None                      # the module said the reading is not valid
        raw = (p[0] << 8) | p[1]
        return _to_millivolts(raw) if raw > 0 else None

    @staticmethod
    def _decode_legacy(p) -> int | None:
        if p is None or len(p) < 3:
            return None
        raw = (p[1] << 8) | p[2]             # bytes 3 and 4 are the USB/charger voltage
        return _to_millivolts(raw) if raw > 0 else None

    def _module_voltage(self, t, dest, key) -> int | None:
        """A docked module's cell voltage in mV, asking only what it answers.

        Which command a module speaks is a property of that module, so it is probed once
        per docking and remembered. Without that, a module that does not implement PRECISE
        costs a full timeout on every single tick, forever, for nothing.
        """
        PRECISE, LEGACY = "precise", "legacy"
        known = self._module_batt.get(key)
        order = ([(PRECISE, C.MOD_GET_PRECISE_BATTERY, self._decode_precise)]
                 if known == PRECISE else
                 [(LEGACY, C.MOD_GET_BATTERY, self._decode_legacy)]
                 if known == LEGACY else
                 [(PRECISE, C.MOD_GET_PRECISE_BATTERY, self._decode_precise),
                  (LEGACY, C.MOD_GET_BATTERY, self._decode_legacy)])
        for name, sub, decode in order:
            mv = decode(_first_payload(t.send_command(dest, C.CAT_MODULE, sub, timeout=1.5)))
            if mv is not None:
                self._module_batt[key] = name
                return mv
        # Neither answered. Deliberately NOT remembered: a module that is charging from flat
        # can start reporting later, and pinning it now would mean never asking again.
        return None

    def _fold(self, key: str, mv: int | None) -> int | None:
        """A rolling median over the last TICK_SAMPLES readings, one reading per tick."""
        if mv is None:
            return None
        buf = self._samples.setdefault(key, [])
        buf.append(mv)
        del buf[:-self.TICK_SAMPLES]
        return sorted(buf)[len(buf) // 2]

    def _mark_disconnected(self, side: str, port: str | None, why: str,
                           fix: dict | None = None) -> dict:
        from datetime import datetime, timezone
        if port:
            self._drop(port)
            self._identity.pop(port, None)
        for k in [k for k in self._samples if k == side or k.startswith(side + ":")]:
            self._samples.pop(k, None)
        snap = {"side": side, "port": port, "connected": False, "error": why,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if fix:
            snap["fix"] = fix       # what the page shows to put it right (port_access)
        self._live[side] = snap
        return snap

    def tick(self, dev) -> dict:
        """One light query of a half. `dev` is an enumerated port (find_naya_serial_ports)."""
        from datetime import datetime, timezone
        with self._lock:
            dest = self._dest_for_side(dev.side)
            try:
                t = self._transport_for(dev.port, dest)
                ident = self._identity.get(dev.port)
                if ident is None:
                    ident = {}
                    p = _first_payload(t.send_command(dest, C.CAT_SYSTEM, C.SYS_GET_FW_VERSION))
                    if p is not None:
                        ident["firmwareVersion"] = format_fw_version(p)
                    p = _first_payload(t.send_command(dest, C.CAT_SYSTEM, C.SYS_GET_HW_ID_NUMBER))
                    if p is not None:
                        try:
                            ident["hardwareId"] = p.decode("ascii")
                        except (UnicodeDecodeError, ValueError):
                            ident["hardwareId"] = hexline(p)
                    p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_ADDRESS))
                    if p is not None and len(p) >= 6:
                        ident["bleAddress"] = ":".join(f"{b:02X}" for b in p[:6])
                    self._identity[dev.port] = ident

                snap: dict = {"side": dev.side, "port": dev.port, "description": dev.description,
                              "serialNumber": dev.serial_number, "connected": True, **ident}
                p = _first_payload(t.send_command(dest, C.CAT_SYSTEM, C.SYS_GET_KB_BATTERY_LEVEL, timeout=0.5))
                mv = self._fold(dev.side, _to_millivolts((p[0] << 8) | p[1]) if p is not None and len(p) >= 2 else None)
                if mv is not None:
                    snap["batteryMillivolts"] = mv
                    snap["batteryPercent"] = _battery_percent(mv)

                # Module: presence from DETECT, type from the handshake address (see status_all).
                handshake = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_SEND_HANDSHAKE, timeout=1.5))
                detect = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_DETECT))
                module = None
                if detect is not None and len(detect) >= 1 and detect[0] != 0:
                    addr = handshake[1] if handshake is not None and len(handshake) >= 2 else None
                    if addr is None:
                        ap = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_ADDRESS))
                        addr = ap[0] if ap is not None and len(ap) >= 1 else None
                    module = {"type": C.module_type_from_address(addr)}
                    if addr is not None:
                        module["address"] = addr
                        module["docked"] = C.module_side_from_address(addr)
                    # The firmware, once per docking: the profile bar shows it in the half's
                    # detail, and status_all already reads it the expensive way.
                    #
                    # Keyed by the HALF, not by the bay. The dock address says type and side,
                    # so every left Tune is address 64 -- two different keyboards shared one
                    # entry and a board swap inherited the previous one's firmware, which the
                    # undock branch below never cleared because nothing was undocked
                    # (SCRUM-98). The serial is what halves_seen already uses to tell one
                    # keyboard from another; older firmware reporting none falls back to the
                    # side, which is exactly the behaviour this had before.
                    fw_key = (dev.serial_number or dev.side, addr)
                    if fw_key not in self._module_fw:
                        fp = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_FW_VERSION))
                        self._module_fw[fw_key] = format_fw_version(fp) if fp is not None else None
                    if self._module_fw.get(fw_key):
                        module["firmwareVersion"] = self._module_fw[fw_key]
                    mmv = self._fold(f"{dev.side}:module",
                                     self._module_voltage(t, dest, fw_key))
                    if mmv is not None:
                        module["batteryMillivolts"] = mmv
                        module["batteryPercent"] = _battery_percent(mmv)
                else:
                    self._samples.pop(f"{dev.side}:module", None)
                    # Undocked: forget its firmware, so a swap is read fresh. Cleared by the
                    # same key shape the entries are written under -- matching on the side
                    # alone stopped clearing anything once the key became the serial.
                    owner = dev.serial_number or dev.side
                    for k in [k for k in self._module_fw if k[0] == owner]:
                        self._module_fw.pop(k, None)
                    for k in [k for k in self._module_batt if k[0] == owner]:
                        self._module_batt.pop(k, None)
                snap["module"] = module
                snap["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._live[dev.side] = snap
                return snap
            except TransportError as e:
                return self._mark_disconnected(dev.side, dev.port, str(e),
                                               fix=getattr(e, "fix", None))

    def tick_all(self) -> dict:
        """Tick every enumerated half; a half that is no longer enumerated is marked gone."""
        if self._released:
            return self.snapshot()      # released: touch nothing, and do not reopen the ports
        seen = set()
        for dev, _others in self.halves_seen():
            seen.add(dev.side)
            self.tick(dev)
        with self._lock:
            for side, snap in list(self._live.items()):
                if side not in seen and snap.get("connected"):
                    self._mark_disconnected(side, snap.get("port"), "no longer on the USB bus")
        return self.snapshot()

    def snapshot(self) -> dict:
        """The last tick's view of every half. In-memory; no device I/O."""
        with self._lock:
            halves = [dict(v) for _k, v in sorted(self._live.items())]
        return {"halves": halves, "released": self._released}

    # --- status ----------------------------------------------------------------

    def status_all(self, verbose: bool = False) -> list[dict]:
        """Query every connected half + module. Structured mirror of nayactl status.

        `verbose` adds the BLE identity block, which costs five more round trips per half.
        It used to be accepted and then ignored -- the Information page needs it, the Device
        Manager's refresh does not, so it is honoured now rather than dropped.
        """
        out: list[dict] = []
        with self._lock:
            for dev, others in self.halves_seen():
                entry: dict = {
                    # Ports of this same half we are not using. Only the ones we PROVED
                    # dead: a half can expose several live CDC interfaces at once (two per
                    # half on 3.28.7), and calling the sibling a leftover warned about
                    # every healthy board on that firmware and offered to ignore a port
                    # that works (SCRUM-90). A genuine ghost still reports, because the
                    # ghost-ahead-of-the-live-one case from SCRUM-82 is exactly the one
                    # where the dead port gets tried and fails.
                    "stalePorts": self._proved_dead(others),
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
                    # May settle on a different interface of the SAME half; see
                    # _open_with_siblings. Both fields below are then restated against the
                    # port we actually reached it on, because reporting the port we failed
                    # on next to "connected": true would be a lie in the payload.
                    dev, t = self._open_with_siblings(dev)
                    dest = self._dest_for_side(dev.side)
                    entry["port"] = dev.port
                    entry["stalePorts"] = self._proved_dead(
                        [d.port for d in self._siblings_of(dev)])
                    entry.update(self._query_half(t, dest, deep=verbose,
                                                  owner=dev.serial_number or dev.side))
                    entry["connected"] = True
                except TransportError as e:
                    entry["error"] = str(e)
                    if getattr(e, "fix", None):
                        entry["fix"] = e.fix
                    self._drop(dev.port)
                out.append(entry)
        return out

    def _query_half(self, t: SerialTransport, dest: int, deep: bool = False,
                    owner: str | None = None) -> dict:
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
                # statusRaw stays, always: `status` is a decode, and a decode can be wrong in a
                # way the bytes cannot. See device/ble_status.py for what is confirmed and what
                # is deliberately left raw. `raw` is dropped from the nested view only because
                # statusRaw sits right beside it holding the identical string.
                ble["statusRaw"] = p.hex()
                decoded = ble_status.decode(p)
                decoded.pop("raw", None)
                ble["status"] = decoded
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
            #  identifies the HALF this module is docked on, so the battery-command
            # cache is shared with the poll instead of each path probing separately. It is
            # passed in because this method sees only a transport: the caller has the device.
            mv = self._module_voltage(t, dest, (owner, addr))
            if mv is not None:
                module["voltage"] = mv
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

    # Every 0xED command's payload begins with a target byte, ahead of the command's own data.
    # A SHORT payload is not rejected -- the device zero-fills the missing trailing bytes -- so
    # sending a bare [value] for a two-parameter command sets the target to that value and the
    # VALUE ITSELF TO ZERO, while acking exactly like a correct frame. That is what `brightness`
    # and `effect` did here: brightness was inert and effect always selected effect 0.
    #
    # MEASURED on the board 2026-09-09, since nothing about it is visible in a response:
    #     [10]      -> off     (target 10, level 0)     [0, 15]   -> dim
    #     [100]     -> off     (target 100, level 0)    [3, 100]  -> full
    #     [200, 15] -> dim     -- the target's VALUE is ignored; only its position matters
    # The one-parameter commands below are correct as they stand: their only parameter IS the
    # target, so an empty payload zero-fills to target 0, and LEDS_OFF with no payload works.
    LED_TARGET = 0

    def led(self, side: str, action: str, value: int | None = None) -> dict:
        def go(t, dest, dev):
            if action == "brightness":
                if value is None:
                    raise ValueError("brightness requires a value 0-255")
                t.send_command(dest, C.CAT_LED, C.LED_ADJUST_BRIGHTNESS,
                               bytes([self.LED_TARGET, value & 0xFF]))
            elif action == "effect":
                if value is None:
                    raise ValueError("effect requires an index")
                t.send_command(dest, C.CAT_LED, C.LED_SELECT_EFFECT,
                               bytes([self.LED_TARGET, value & 0xFF]))
            elif action in self._LED_ACTIONS:
                t.send_command(dest, C.CAT_LED, self._LED_ACTIONS[action])
            else:
                raise ValueError(f"unknown LED action: {action}")
            return {"ok": True, "side": dev.side, "action": action, "value": value}
        return self._with_transport(side, go)

    # Persistent LED SETTINGS, distinct from the live commands above. NayaFlow never sent these on
    # flash (two captures, 2026-09-01 -- see docs/write-protocol-spec.md rule 12); NayaCore sends
    # them live, and PR #6 on nayactl recovered the opcodes. Not in the vendored nayactl yet --
    # defined here, and flagged for the next upstream PR alongside PID 0x0137. All are CAT_LED and,
    # like the live commands, carry [target, value] with the target pinned to 0.
    _LED_SET_SCANMODE = 0x1012        # SET_SCANMODE_PWM        -> led_scan_mode (bool)
    _LED_SET_MAX_BRIGHTNESS = 0x1013  # SET_LED_MAX_BRIGHTNESS  -> led_max_brightness (0-100)
    _LED_SET_LAYER_OVERRIDE = 0x1014  # SET_LED_LAYER_OVERRIDE  -> led_action_override (enum int)
    _LED_SETTINGS = {
        "scan_mode": _LED_SET_SCANMODE,
        "max_brightness": _LED_SET_MAX_BRIGHTNESS,
        "layer_override": _LED_SET_LAYER_OVERRIDE,
    }

    def run_recovery_op(self, side: str, op_id: str, opts: dict | None = None, *, force: bool = False) -> dict:
        """Run one recovery/troubleshooting procedure. DISABLED ops refuse even with force -- they
        are wired for review and gated until each is tested on a donor unit. Every op also requires
        force=True, so the UI confirmation is not the only guard. The exact frame is built by
        recovery_ops.frame_for (pinned by tests), so what ships is what was reviewed."""
        from . import recovery_ops as ro
        from .commands import CommandError   # lazy: commands imports this module at load
        op = ro.BY_ID.get(op_id)
        if op is None:
            raise ValueError(f"unknown recovery op: {op_id}")
        if not op.enabled:
            raise CommandError(f"{op.label} is wired but disabled until it is tested on a donor "
                               f"unit ({op.needs}). Nothing was sent.")
        if not force:
            raise CommandError(f"{op.label} is a device write and needs an explicit confirmation.")
        cat, sub, payload = ro.frame_for(op_id, opts or {})

        def go(t, dest, dev):
            t.send_command(dest, cat, sub, payload, allow_dangerous=True)
            return {"ok": True, "side": dev.side, "op": op_id,
                    "sent": {"cat": cat, "sub": sub, "payload": payload.hex()}}
        return self._with_transport(side, go)

    def module_file_fw_version(self, side: str = "left") -> dict:
        """The module firmware version stored ON THE KEYBOARD (MODULE_FILE_FW_VERSION, 0xDE/0x100A):
        the VERSION file of the FlashMemory.bin bundle in its modules slot, as opposed to
        GET_MODULE_FW_VERSION, which is what a docked module itself runs. A read. NayaCore compares
        the two after an upload ("Module firmware version image does not match stored module
        firmware version"); this is the half of that check that needs no module docked, and it is
        how a bundle upload is verified after the reboot, since a LittleFS partition has no MCUboot
        hash to read back. Never seen on hardware: `raw` stays beside the decode."""
        def go(t, dest, dev):
            p = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_FILE_FW_VERSION))
            if p is None:
                raise TransportError("the half did not answer MODULE_FILE_FW_VERSION")
            return {"side": dev.side, "raw": p.hex(), "version": format_fw_version(p),
                    "validated": False}
        return self._with_transport(side, go)

    def led_setting(self, side: str, setting: str, value: int) -> dict:
        """Send one persistent LED setting live. All three verified on hardware (brightness and
        scan mode 2026-09-13, layer override 2026-09-16). max_brightness (0x1013) is a persistent
        ceiling: 0 darks the array and survives a
        reboot, so the caller (and the test) must restore a non-zero value; it is refused as 0 here
        as a guard, since nothing legitimately wants a permanent-dark write from this path."""
        sub = self._LED_SETTINGS.get(setting)
        if sub is None:
            raise ValueError(f"unknown LED setting: {setting} (have {sorted(self._LED_SETTINGS)})")
        v = int(value) & 0xFF
        if setting == "max_brightness" and v == 0:
            raise ValueError("refusing to set max_brightness to 0: it darks the board persistently. "
                             "Use a value 1-100.")

        def go(t, dest, dev):
            t.send_command(dest, C.CAT_LED, sub, bytes([self.LED_TARGET, v]))
            return {"ok": True, "side": dev.side, "setting": setting, "value": v, "subcmd": sub}
        return self._with_transport(side, go)

    def restore_lighting(self, side: str = "left") -> dict:
        """Put both halves back to the stored colours and animation after an LED effect key.

        Reads the layer list and writes it straight back. Measured 2026-09-10: that one frame, sent
        to the left, clears a runtime effect on BOTH halves, and nothing else does short of a power
        cycle. NayaFlow has no equivalent; its flash only writes the list when layers change, which
        is why "flash from NayaFlow" never restored lighting either. Every OpenFlow flash now ends
        with the same write (flash._lighting_restore_ops); this is the button for when nothing
        needs flashing."""
        from . import flash as F
        from . import keymap_read as K
        from . import remap as R

        def go(t, dest, dev):
            r = [x for x in t._send_raw(K._build(dest, K.READ_LAYER_LIST), 2.0) if x.valid]
            raw = bytes(r[0].payload) if r else b""
            idxs, uuids, anims = K.parse_layer_list(raw)
            if not idxs:
                raise TransportError("the board returned no layer list; nothing to restore")
            payload = F.lighting_restore_payload({i: R.layer_uuid_bytes(u) for i, u in uuids.items()}, anims)
            for frame in R.frames_for(dest, R.WRITE_LAYER_LIST, payload):
                t._send_raw(frame, 2.0)
            return {"ok": True, "side": dev.side, "layers": len(idxs),
                    "animations": {i: K.LAYER_ANIMATIONS.get(a, a) for i, a in anims.items()}}
        return self._with_transport(side, go)

    # --- Bluetooth profile slots ----------------------------------------------
    # Five slots, 0-4. NayaCore's own validation strings fix the wire form of SELECT and CLEAR:
    # "Invalid parameter size (%1) for SEL/CLEAR_BLE_PROFILE, should be 1" and "Invalid profile
    # (%1) for SEL/CLEAR_BLE_PROFILE, should be less than 5" -- one byte, the slot index.
    # NayaFlow's keys reach 1-4 only; slot 0 is never offered and is most likely the dongle's,
    # so it is reported as reserved and refused unless the caller says otherwise. The active slot
    # and its numbering were measured 2026-09-10: BT_DEVICE_n selects slot n, the status blob
    # reports the same n, and it persists across a power cycle (tests/test_ble_status.py).
    # Selecting over the cable is assumed to do what the key does; the read-back after the
    # write says whether the half agreed.
    BLE_SLOTS = 5
    BLE_RESERVED_SLOT = 0

    def _check_slot(self, index, allow_reserved: bool) -> int:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < self.BLE_SLOTS:
            raise ValueError(f"Bluetooth slot must be 0-{self.BLE_SLOTS - 1}, got {index!r}")
        if index == self.BLE_RESERVED_SLOT and not allow_reserved:
            raise ValueError("slot 0 is reserved: NayaFlow never selects it and it is most likely "
                             "the dongle's. Pass allowReserved to override.")
        return index

    def ble_profiles(self, side: str = "left") -> dict:
        """The five Bluetooth slots as the half reports them: which is active, which hold a bond."""
        def go(t, dest, dev):
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_STATUS))
            if p is None:
                raise TransportError(f"the {dev.side} half returned no Bluetooth status")
            d = ble_status.decode(p)
            slots = [{"index": pr["index"], "active": bool(pr["isActive"]),
                      "bonded": bool(pr.get("bonded") or pr["hasPeerData"]),
                      "connected": bool(pr.get("connected")),
                      "peerAddress": pr.get("peerAddress"),
                      "reserved": pr["index"] == self.BLE_RESERVED_SLOT,
                      "flags": pr["activeFlags"]}
                     for pr in d.get("profiles") or []]
            return {"ok": True, "side": dev.side, "activeProfile": d.get("activeProfile"),
                    "hostConnected": bool(d.get("hostConnected")),
                    "slots": slots, "localAddress": d.get("localAddress"), "statusRaw": p.hex()}
        return self._with_transport(side, go)

    def select_ble_profile(self, side: str, index: int, allow_reserved: bool = False) -> dict:
        """Make slot `index` the active one -- what the BT_DEVICE_n key does. Read back after."""
        index = self._check_slot(index, allow_reserved)

        def go(t, dest, dev):
            t.send_command(dest, C.CAT_BLE, C.BLE_SELECT_PROFILE, bytes([index]))
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_STATUS))
            now = ble_status.decode(p).get("activeProfile") if p else None
            return {"ok": now == index, "side": dev.side, "requested": index, "activeProfile": now,
                    "note": None if now == index else
                    "the half took the command but still reports a different active slot"}
        return self._with_transport(side, go)

    def clear_ble_profile(self, side: str, index: int, force: bool = False) -> dict:
        """Drop slot `index`'s bond and start pairing for it -- what the BT_CLEAR key does to the
        selected slot. Destructive: the bond is gone. Requires force."""
        index = self._check_slot(index, allow_reserved=False)
        if not force:
            raise DangerousCommandError("clearing a Bluetooth slot drops its bond and starts "
                                        "pairing; confirm explicitly")

        def go(t, dest, dev):
            t.send_command(dest, C.CAT_BLE, C.BLE_CLEAR_PROFILE, bytes([index]))
            p = _first_payload(t.send_command(dest, C.CAT_BLE, C.BLE_GET_STATUS))
            d = ble_status.decode(p) if p else {}
            still = next((pr for pr in d.get("profiles") or [] if pr["index"] == index), None)
            return {"ok": True, "side": dev.side, "cleared": index,
                    "activeProfile": d.get("activeProfile"),
                    "bonded": bool(still["hasPeerData"]) if still else None}
        return self._with_transport(side, go)

    # --- text protocol ---------------------------------------------------------

    def text_command(self, side: str, command: str, force: bool = False) -> dict:
        def go(t, dest, dev):
            reply = t.send_text(command, allow_dangerous=force)
            return {"ok": True, "side": dev.side, "command": command, "reply": reply}
        return self._with_transport(side, go)

    def dump_settings(self, side: str) -> dict:
        return self.text_command(side, "dump_settings")

    # --- keymap read (REMAP) ---------------------------------------------------

    def read_keymap(self, side: str = "left") -> dict:
        """Read the full board keymap (bindings + LED colours) off a connected half.

        The central/left half holds the whole-board map, so default to it. Returns
        the raw read for db.keymap_import to translate + persist. Read-only."""
        from . import keymap_read

        return self._with_transport(side, lambda t, dest, dev: keymap_read.read_keymap(t, dest))

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

        read = self._with_transport(side, lambda t, dest, dev: keymap_read.read_module_configs(t, dest))
        return {
            "list": read["list"].hex(),
            "by_uuid": F.slot_map_for(read["list"]),
            "slots": {slot: [{"field": f, "type": ty, "value": v.hex()} for f, ty, v in recs]
                      for slot, recs in read["slots"].items()},
        }

    # --- troubleshooting -------------------------------------------------------

    def spi_flash_test(self, side: str) -> dict:
        """Read-only SPI flash self-test (0xFA/0x1001). Does NOT format/erase."""
        def go(t, dest, dev):
            responses = t.send_command(dest, C.CAT_FLASH, C.FLASH_TEST, timeout=3.0)
            payload = _first_payload(responses)
            # `raw` stays and callers should keep showing it. The decode was derived from
            # NayaCore's output format and checked against both halves of a healthy board on
            # 2026-09-10; the one thing a healthy board cannot confirm is the order of the five
            # return codes inside a partition, which the decode's `validation` field says.
            # See device/spi_flash_test.py.
            decoded = spi_flash_test.decode(payload)
            decoded.pop("raw", None)
            return {
                "ok": payload is not None,
                "side": dev.side,
                "raw": payload.hex() if payload else "",
                "diagnosis": decoded,
                "summary": spi_flash_test.summary(decoded),
            }
        return self._with_transport(side, go)

    def clear_ble_devices(self, side: str, force: bool = False) -> dict:
        """Clear BLE bonds (text: clear_bonds). Destructive: requires force."""
        return self.text_command(side, "clear_bonds", force=force)

    # --- keyscan (blocking; run on a worker thread) ----------------------------

    def keyscan(self, side: str, duration: float, callback: Callable[[dict], None]) -> None:
        """Toggle keyscan mode on, stream events for `duration`s, then toggle off."""
        def go(t, dest, dev):
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
        self._with_transport(side, go)

    # --- helpers ---------------------------------------------------------------

    def _note_port(self, port: str, ok: bool) -> None:
        self._port_health[port] = {"ok": ok, "at": time.time()}

    def _proved_dead(self, ports: list[str]) -> list[str]:
        """Of these ports, the ones something actually tried and that actually failed.

        Evidence, not inference. A port nobody has opened says nothing about itself, and
        on a keyboard whose half exposes two live interfaces the unused one is not a
        leftover -- it answers perfectly well, we simply are not using it.
        """
        return [p for p in ports
                if self._port_health.get(p, {}).get("ok") is False]

    def _rank(self, dev) -> tuple:
        """Best port first: one that answered, then one never tried, then one that failed --
        oldest failure first, so a port that has since recovered gets another go rather than
        being blacklisted for the life of the process."""
        h = self._port_health.get(dev.port)
        if h is None:
            return (1, 0.0, dev.port)
        return ((0, -h["at"], dev.port) if h["ok"] else (2, h["at"], dev.port))

    def visible_ports(self) -> list:
        """Enumerated ports minus the ones the user told us to ignore."""
        return [d for d in find_naya_serial_ports() if d.port not in self._ignored]

    def halves_seen(self) -> list[tuple]:
        """One (device, [other ports]) per PHYSICAL half.

        Two ports reporting the same serial number are one keyboard -- that is what a half
        looks like after it re-enumerates and Windows keeps the old node. They are grouped
        rather than dropped, and the ports not chosen are handed back, so the page can say
        they exist instead of silently hiding them. A missing serial (older firmware) falls
        back to side and product id, the next best thing that still names one unit.
        """
        groups: dict = {}
        for d in self.visible_ports():
            groups.setdefault(d.serial_number or f"{d.side}:{d.pid}", []).append(d)
        out = []
        for devs in groups.values():
            ordered = sorted(devs, key=self._rank)
            out.append((ordered[0], [x.port for x in ordered[1:]]))
        # LEFT then RIGHT, always. The order used to follow DISCOVERY, so whichever half
        # enumerated first came first -- and the Devices page, which draws them in the order it
        # is given, put the right half on the left of the screen whenever the right happened to
        # come up first (SCRUM-89, seen on a board whose right half led by 1.7 s). Sorted here
        # rather than in status_all because all three callers want the same guarantee and a
        # discovery-ordered list is useful to none of them. The port is the tiebreak so the
        # order is total, never incidental.
        return sorted(out, key=lambda t: (_SIDE_ORDER.get(t[0].side, len(_SIDE_ORDER)),
                                          t[0].side or "", t[0].port or ""))

    # --- the ignore list -------------------------------------------------------

    def ignored_ports(self) -> list[str]:
        return sorted(self._ignored)

    def ignore_port(self, port: str) -> dict:
        """Leave a port alone: no resolution, no tick, not on the Devices page."""
        with self._lock:
            self._drop(port)
            self._ignored.add(port)
            _save_ignored(self._ignored)
        return {"ignored": self.ignored_ports()}

    def unignore_port(self, port: str) -> dict:
        with self._lock:
            self._ignored.discard(port)
            self._port_health.pop(port, None)   # give it a clean try next time
            _save_ignored(self._ignored)
        return {"ignored": self.ignored_ports()}

    def _ranked_for_side(self, side: str) -> list:
        """Every port for this side, best first.

        Prefers one that has answered. It used to take the first match and stop, which is how
        a ghost port ahead of the live one broke every read and flash in the app (SCRUM-82).
        It also no longer falls back to a device of a DIFFERENT side: that turned 'the left
        half is not plugged in' into silently talking to the right one, which on a flash
        means writing to the wrong half.
        """
        cands = [d for d in self.visible_ports() if d.side == side]
        if not cands:
            seen = {d.side for d in self.visible_ports()}
            extra = f" Connected: {', '.join(sorted(seen))}." if seen else ""
            raise TransportError(f"No {side} device found. Is it connected via USB?{extra}")
        return sorted(cands, key=self._rank)

    def _require_side(self, side: str):
        """The single best port for this side."""
        return self._ranked_for_side(side)[0]

    def _siblings_of(self, dev) -> list:
        """The other ports that are provably the SAME PHYSICAL HALF as `dev`, best first.

        Same serial number, nothing looser. Two Creates attached means two devices that
        both call themselves "left", and falling through to the other one would read the
        wrong keyboard -- or, on a flash, write to it. A half that reports no serial
        (older firmware does exist) gets no siblings, because then nothing proves the two
        ports belong to the same unit and a guess here is not worth the failure mode.

        Returns [] rather than raising when there is nothing to enumerate: this runs on a
        path that could not fail before, and it must not start failing there.
        """
        sn = getattr(dev, "serial_number", None)
        if not sn:
            return []
        same = [d for d in self.visible_ports()
                if d.port != dev.port and d.side == dev.side
                and getattr(d, "serial_number", None) == sn]
        return sorted(same, key=self._rank)

    def _connect_side(self, side: str):
        """(device, transport) for this side, trying sibling interfaces before giving up.

        A half can present several CDC interfaces at once and only one of them answers;
        which one is not predictable (on 3.28.7 the right half answers MI_02 and the left
        MI_03, neither MI_00). Until _port_health has learned better, _rank leaves them
        tied and the COM NAME decides, so a cold start can pick the interface that does not
        answer and fail an operation on a healthy board (SCRUM-90).

        Trying the sibling costs nothing where there is none, which is every half on 3.41,
        so the supported baseline is unaffected. Each attempt records the port's health, so
        the fallback happens once and later calls go straight to the interface that works.
        """
        # _require_side stays the ONE place a side becomes a port. Going around it would
        # bypass the seam the rest of the service and its tests are built on.
        return self._open_with_siblings(self._require_side(side))

    def _open_with_siblings(self, primary):
        """(device, transport), trying this half's other interfaces before giving up.

        Shared by _connect_side and status_all so the Devices page and every command agree
        about which port reaches a half. They did not before: status_all opened the port
        halves_seen guessed and reported the half DISCONNECTED when that guess was the deaf
        interface, on a board that was working perfectly.

        The error raised when everything fails is the FIRST one, which is the primary's, so
        a half with no siblings reports exactly what it always did.
        """
        first_error = None
        for dev in [primary, *self._siblings_of(primary)]:
            try:
                return dev, self._transport_for(dev.port, self._dest_for_side(dev.side))
            except port_access.PortAccessDenied:
                raise          # a permissions problem is identical on every sibling
            except TransportError as e:
                if str(e) == self.RELEASED_ERROR:
                    raise      # released is a decision of ours, not a port that is deaf
                if first_error is None:
                    first_error = e
        raise first_error
