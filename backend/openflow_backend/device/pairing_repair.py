"""The guided split-link repair: NayaCore's Pairing operation as ONE reviewed sequence.

WIRED, DISABLED, NEVER RUN. `PAIRING_REPAIR_ENABLED` ships False, and underneath it every write
the sequence sends is a recovery op that itself ships disabled (recovery_ops.py), so nothing here
can reach a keyboard until both gates are opened after the sequence is watched on a spare pair.
Planning and verifying are reads and work today.

WHERE THE SEQUENCE COMES FROM. NayaCore 6.11.0's Naya_DeviceManager_Pairing.cpp leaves its step
list in the binary in order (extracted/NayaFlow-1.25.1/strings/core-strings.txt:5481-5492):

    Pairing: Setting new pair address to %1 for device: %2.
    Pairing to known pair address: %1 for device: %2.
    repair_ble_address          -> SET_PAIR_ADDRESS (0xBE/0x1001, 6-byte address)
    wait_300ms
    clear_all_split_links       -> CLEAR_ALL_SPLIT_LINKS (0xBE/0x1010)
    unpair_all_pairs            -> UNPAIR_ALL (0xBE/0x1004)
    wait_1000ms
    Pairing: Waiting for peer %1 before normal_reset for device: %2.
    normal_reset                -> RESET/NORMAL (0xEE/0x10CE)

with the Pairing operation's own phases ExchangeBLEAddresses -> WaitForPairingPeerBeforeNormalReset
-> VerifyBLEAddresses ("Exchanging BLE addresses between devices." / "Waiting for pairing peer
before device reset." / "Verifying BLE addresses were exchanged successfully."). Its refusals are
reused verbatim: "Pairing failed: missing device(s) (left=%1, right=%2)" and "Devices have
different firmware versions".

The "store before clear" rule is borrowed from a SIBLING operation, NayaCore's ClearBLEDevices
(Naya_DeviceManager_ClearBLEDevices.cpp; phases CheckBLEFWVersion, WaitForPairAddress,
StorePairedHalfAddressBeforeClear, ClearConnections, VerifyConnectionsCleared, Respawn,
RecheckBLEStatus, WaitForBLEStatus, VerifyBLEFWVersion; "Storing paired half address before
clearing connections."), which it runs after a firmware update crosses the BLE version and then
re-pairs "to known pair address". That is where the step names CheckBLEFWVersion /
StorePairedHalfAddressBeforeClear / Respawn / RecheckBLEStatus in the plan below come from; the
WRITES and their order are the Pairing operation's.

THE ORDER IS THE SAFETY PROPERTY. The partner address is set on each half FIRST and stored
durably here BEFORE any clearing; the clears come after. Clear first and the only copy of what
to restore is gone. That is why this is one sequence and not four buttons.

WHAT IT COSTS. `unpair_all_pairs` drops every Bluetooth bond on both halves, hosts included, not
just the split link. NayaCore does exactly that; so does this, and the confirmation says so.

The two waits are host-side pauses between commands (NayaCore's `wait_*` steps are queue meta
commands, "WAIT meta command duration %1 ms exceeds max %2 ms, clamping"); the "wait for peer"
is: send nothing to either half until both have taken every earlier step.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import recovery_ops as ro

PAIRING_REPAIR_ENABLED = os.environ.get("OPENFLOW_ENABLE_PAIRING_REPAIR") == "1"
# Driven by the environment rather than edited to True for a session, so it cannot be
# committed on by accident. Unset, or anything but "1", is off. The per-op gates in
# recovery_ops still apply underneath: this one alone sends nothing.

WAIT_AFTER_SET_PAIR_MS = 300        # NayaCore: wait_300ms
WAIT_AFTER_UNPAIR_MS = 1000         # NayaCore: wait_1000ms
RECORD_KEY = "openflow.pairing_record"

# NayaCore's own refusals, verbatim, so a user who has seen NayaFlow's recognises them.
MISSING = "Pairing failed: missing device(s) (left={left}, right={right})"
DIFFERENT_FW = "Devices have different firmware versions"


class PairingRefused(RuntimeError):
    """An interlock said no. The message is the reason, for showing to a user."""


@dataclass
class Step:
    name: str                     # NayaCore's phase or alias name
    kind: str                     # read | store | write | wait | verify
    side: str | None = None       # left | right | both | None
    op: str | None = None         # recovery op id for a write
    opts: dict = field(default_factory=dict)
    frame: tuple | None = None    # (cat, sub, payload) for a write, from the pinned registry
    ms: int = 0                   # for a wait
    detail: str = ""

    def public(self) -> dict:
        cmd = None
        if self.frame:
            cat, sub, payload = self.frame
            cmd = f"{cat:#04x}/{sub:#06x} {payload.hex() or '(empty)'}"
        return {"name": self.name, "kind": self.kind, "side": self.side, "op": self.op,
                "opts": self.opts, "command": cmd, "ms": self.ms, "detail": self.detail}


@dataclass
class PairingPlan:
    """What the repair WOULD do to these two halves. Produced from a deep status read; sends
    nothing. `record` is what gets stored before anything is cleared; `arm_token` is derived
    from the four addresses, so a token minted for one pair of halves (or for these halves before
    their addresses changed) cannot arm a run on another."""
    left: dict
    right: dict
    record: dict
    arm_token: str
    steps: list[Step]
    notes: list[str] = field(default_factory=list)

    @property
    def ops(self) -> list[str]:
        return sorted({s.op for s in self.steps if s.kind == "write" and s.op})

    def public(self) -> dict:
        return {"enabled": PAIRING_REPAIR_ENABLED, "armToken": self.arm_token,
                "record": self.record, "steps": [s.public() for s in self.steps],
                "notes": self.notes, "ops": self.ops,
                "opsDisabled": [o for o in self.ops if not ro.BY_ID[o].enabled]}

    def describe(self) -> str:
        lines = [f"pairing repair: left {self.left['bleAddress']} <-> right {self.right['bleAddress']}",
                 f"  store first: {json.dumps(self.record['left'])} / {json.dumps(self.record['right'])}"]
        for s in self.steps:
            p = s.public()
            lines.append(f"  {s.name:36} {s.kind:6} {s.side or '-':5} {p['command'] or ''} {s.detail}")
        lines.append(f"  arm token: {self.arm_token}")
        return "\n".join(lines)


def _addr(x) -> str:
    return str(x or "").upper()


def _half(halves: list[dict], side: str) -> dict | None:
    return next((h for h in halves or [] if h.get("side") == side and h.get("connected")), None)


def _snapshot(h: dict) -> dict:
    ble = h.get("ble") or {}
    return {"port": h.get("port"), "serialNumber": h.get("serialNumber"),
            "bleAddress": _addr(h.get("bleAddress")) or None,
            "pairAddress": _addr(ble.get("pairAddress")) or None,
            "firmwareVersion": h.get("firmwareVersion"),
            "bleFirmwareVersion": ble.get("firmwareVersion"),
            "bleName": ble.get("name")}


def plan(halves: list[dict]) -> PairingPlan:
    """Every interlock, then the sequence. Pure: `halves` is DeviceService.status_all(verbose=True)."""
    left, right = _half(halves, "left"), _half(halves, "right")
    if left is None or right is None:
        raise PairingRefused(MISSING.format(left=left is not None, right=right is not None)
                             + ". Both halves must be on USB; the sequence exchanges their addresses.")
    L, R = _snapshot(left), _snapshot(right)
    if L["firmwareVersion"] != R["firmwareVersion"]:
        raise PairingRefused(f"{DIFFERENT_FW} (left {L['firmwareVersion']}, right "
                             f"{R['firmwareVersion']}). NayaCore refuses to pair them and so does "
                             "this; bring both halves to one version first.")
    notes = []
    if L["bleFirmwareVersion"] and R["bleFirmwareVersion"]:
        if L["bleFirmwareVersion"] != R["bleFirmwareVersion"]:
            raise PairingRefused(f"the halves run different BLE firmware (left "
                                 f"{L['bleFirmwareVersion']}, right {R['bleFirmwareVersion']}); "
                                 "NayaCore checks this first (CheckBLEFWVersion) and so does this.")
    else:
        notes.append("BLE firmware version not reported by both halves; CheckBLEFWVersion could "
                     "not be applied.")
    if not L["bleAddress"] or not R["bleAddress"]:
        raise PairingRefused("a half did not report its own BLE address (BLE_GET_ADDRESS), so "
                             "there is nothing to exchange. Nothing is cleared without it.")
    if L["bleAddress"] == R["bleAddress"]:
        raise PairingRefused("both halves report the same BLE address; refusing to point a half "
                             "at itself.")
    for s in (L, R):
        if not s["pairAddress"]:
            notes.append(f"the {'left' if s is L else 'right'} half reports no pair address; "
                         "it will be stored as none.")

    record = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
              "left": L, "right": R,
              "willSet": {"left": R["bleAddress"], "right": L["bleAddress"]},
              "why": "stored before any clearing, so the addresses can be restored by hand if "
                     "the sequence stops"}
    arm = hashlib.sha256(f"{L['bleAddress']}>{R['bleAddress']};{L['pairAddress']}>"
                         f"{R['pairAddress']}".encode()).hexdigest()[:16]

    def write(name, side, op, opts=None, detail=""):
        return Step(name, "write", side, op, opts or {}, ro.frame_for(op, opts or {}), detail=detail)

    steps = [
        Step("CheckBLEFWVersion", "read", "both",
             detail=f"both halves on Create {L['firmwareVersion']}, BLE "
                    f"{L['bleFirmwareVersion'] or 'unreported'}"),
        Step("WaitForPairAddress", "read", "both",
             detail=f"left is paired to {L['pairAddress'] or 'nothing'}, right to "
                    f"{R['pairAddress'] or 'nothing'}"),
        Step("StorePairedHalfAddressBeforeClear", "store", None,
             detail="both halves' own and pair addresses written to the backups folder and the "
                    "database BEFORE anything is sent"),
        write("ExchangeBLEAddresses", "left", "ble_set_pair_address", {"mac": R["bleAddress"]},
              f"left's partner := {R['bleAddress']} (the right half's own address)"),
        write("ExchangeBLEAddresses", "right", "ble_set_pair_address", {"mac": L["bleAddress"]},
              f"right's partner := {L['bleAddress']} (the left half's own address)"),
        Step("wait_300ms", "wait", "both", ms=WAIT_AFTER_SET_PAIR_MS, detail="NayaCore's pause"),
        write("ClearConnections", "left", "ble_clear_all_split_links", detail="drop the old split link"),
        write("ClearConnections", "right", "ble_clear_all_split_links", detail="drop the old split link"),
        write("ClearConnections", "left", "ble_unpair_all",
              detail="drop EVERY bond on this half, hosts included (NayaCore's unpair_all_pairs)"),
        write("ClearConnections", "right", "ble_unpair_all",
              detail="drop EVERY bond on this half, hosts included (NayaCore's unpair_all_pairs)"),
        Step("wait_1000ms", "wait", "both", ms=WAIT_AFTER_UNPAIR_MS, detail="NayaCore's pause"),
        Step("WaitForPairingPeerBeforeNormalReset", "wait", "both",
             detail="neither half is reset until both have taken every step above"),
        write("Respawn", "left", "reset_normal", detail="normal reset; the link is rebuilt on boot"),
        write("Respawn", "right", "reset_normal", detail="normal reset; the link is rebuilt on boot"),
        Step("VerifyBLEAddresses", "verify", "both",
             detail="after re-enumeration: each half's pair address must be the other's own"),
        Step("RecheckBLEStatus", "verify", "both",
             detail="the split link in BLE_GET_STATUS must show the partner and be up"),
    ]
    return PairingPlan(left=L, right=R, record=record, arm_token=arm, steps=steps, notes=notes)


def store_record(record: dict) -> dict:
    """Durable, in two places: a JSON file beside the backups (a person can find it) and the
    settings table (the app can show it). Raises if either write fails, and the caller must then
    send nothing."""
    from ..db import device_state as ds
    from ..db.backup import backups_dir
    from ..db.database import connect
    d = backups_dir() / "pairing-records"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"pairing-{record['at'].replace(':', '').replace(' ', 'T')}.json"
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    conn = connect()
    try:
        ds._write(conn, record, RECORD_KEY)
        conn.commit()
    finally:
        conn.close()
    return {"file": str(path), "key": RECORD_KEY}


def execute(service, p: PairingPlan, *, arm: str, force: bool, store=None, sleep=time.sleep) -> dict:
    """Run the sequence. Refuses, in this order and before sending anything: the module gate; a
    stale or wrong arm token; no explicit force; any op in the plan still disabled (a sequence
    that could stop halfway through is worse than one that never starts); a record that could
    not be stored. Only then are frames sent, through DeviceService.run_recovery_op so the
    per-op gate and the pinned frames apply."""
    if not PAIRING_REPAIR_ENABLED:
        raise PairingRefused("the guided pairing repair is wired but disabled until it is watched "
                             "on a spare pair. Nothing was sent.")
    if arm != p.arm_token:
        raise PairingRefused("not armed. Pass arm= the token of a plan made against these halves' "
                             f"current addresses ({p.arm_token}); it changes when they do.")
    if not force:
        raise PairingRefused("this forgets every Bluetooth bond on both halves, hosts included, "
                             "and needs an explicit confirmation.")
    disabled = [o for o in p.ops if not ro.BY_ID[o].enabled]
    if disabled:
        raise PairingRefused(f"the sequence needs these recovery ops enabled first: {disabled}. "
                             "Running with some of them disabled would stop between the address "
                             "exchange and the clear. Nothing was sent.")
    try:
        stored = (store or store_record)(p.record)    # STORE FIRST
    except Exception as e:                            # noqa: BLE001 -- any failure means no send
        raise PairingRefused(f"the address record could not be stored ({type(e).__name__}: {e}), "
                             "so nothing was sent: without it there is no copy of what to "
                             "restore.") from e
    sent = []
    for s in p.steps:
        if s.kind == "write":
            r = service.run_recovery_op(s.side, s.op, s.opts, force=True)
            sent.append({"step": s.name, "side": s.side, "op": s.op, "result": r})
        elif s.kind == "wait" and s.ms:
            sleep(s.ms / 1000)
    return {"ok": True, "stored": stored, "sent": sent, "expect": p.record["willSet"],
            "next": "wait for both halves to re-enumerate, then GET /api/pairing-repair/verify"}


def verify(halves: list[dict], expected: dict | None = None) -> dict:
    """VerifyBLEAddresses + RecheckBLEStatus, pure: the bond verdict (each half's pair address is
    the other's own address) and the link state, from a deep status read. `expected` is a plan's
    record['willSet']; with it the verdict also says whether the addresses are the ones the
    sequence set."""
    from .service import pairing_report
    report = pairing_report(halves)
    out = {"state": report.get("state"), "detail": report.get("detail"),
           "links": report.get("links") or {}}
    L, R = _half(halves, "left"), _half(halves, "right")
    if L and R:
        out["addresses"] = {"left": _snapshot(L), "right": _snapshot(R)}
    if expected and L and R:
        got = {"left": _snapshot(L)["pairAddress"], "right": _snapshot(R)["pairAddress"]}
        out["matchesPlan"] = {k: got[k] == _addr(expected.get(k)) for k in ("left", "right")}
    return out
