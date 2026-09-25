"""Recovery / troubleshooting procedures recovered from the NayaFlow / NayaCore v6.11.0 teardown.

Every one of these is a DEVICE WRITE, most destructive. They are wired and their exact frames are
pinned by tests, but every op ships DISABLED (`enabled=False`): the send path refuses a disabled
op even with force, so nothing here can run until it is enabled one at a time on a donor unit. The
UI lists them (gated, behind a per-op confirmation) so the eventual test just flips `enabled`.

Correctness is checked against NayaCore's own strings, not guessed:
  * opcodes are nayactl's (device/remap.py + _vendor/nayactl/constants.py);
  * payload SHAPES come from NayaCore v6.11.0's validation strings in
    extracted/NayaFlow-1.25.1/strings/core-strings.txt (e.g. "Invalid parameter size (%1) for
    SET_HOST_OS, should be 1"; "Invalid host_os (%1) ... should be less than %2"; the [SET HOST OS
    0x / MODULE BATTERY RECOVERY 0x / RESET MODULE 0x ...] send-log formats at 5719-5758);
  * each op records whether its payload is CONFIRMED (a validation string / capture pins it) or
    INFERRED (opcode known, exact bytes unproven -- the reason it stays disabled until tested).

The pairing-repair SEQUENCE (the sharpest gap) is NayaCore's, recovered as the state-machine names
CheckBLEFWVersion -> WaitForPairAddress -> StorePairedHalfAddressBeforeClear -> ClearConnections ->
VerifyConnectionsCleared -> (exchange) -> Respawn -> RecheckBLEStatus -> WaitForBLEStatus ->
VerifyBLEFWVersion. The load-bearing safety property: STORE the partner address BEFORE clearing --
clear first and the only copy of what to restore is gone. That ordering is enforced by the guided
op below.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from .._vendor.nayactl import constants as C
from . import remap as R

CONFIRMED = "confirmed"   # a NayaCore validation string or a capture pins the payload
INFERRED = "inferred"     # opcode known, exact bytes unproven -- keep disabled until a donor test


@dataclass(frozen=True)
class RecoveryOp:
    id: str
    label: str
    desc: str
    danger: str                       # "reset" | "recovery" | "destructive"
    cat: int
    sub: int
    provenance: str                   # CONFIRMED | INFERRED (payload shape)
    confirm: str                      # the exact text the UI must show before running
    enabled: bool = False             # gated until tested on a donor unit
    args: tuple = ()                  # names of required args (e.g. ("mac",), ("os",))
    build_payload: Callable[[dict], bytes] | None = None   # args -> payload; default empty
    needs: str = "donor unit"         # why it is disabled / what unblocks it

    def payload(self, opts: dict) -> bytes:
        return self.build_payload(opts) if self.build_payload else b""


def _mac_bytes(opts: dict) -> bytes:
    mac = (opts.get("mac") or "").replace(":", "").replace("-", "")
    raw = bytes.fromhex(mac)
    if len(raw) != 6:
        raise ValueError("a BLE address must be 6 bytes (12 hex digits)")
    return raw


def _host_os_byte(opts: dict) -> bytes:
    # NayaCore: SET_HOST_OS payload is 1 byte, value < 2. Enum order from core-strings.txt
    # (WINDOWS_OS then MAC_OS): 0 = Windows, 1 = macOS.
    os = opts.get("os")
    mapping = {"windows": 0, "win": 0, "mac": 1, "macos": 1}
    if isinstance(os, int):
        v = os
    else:
        v = mapping.get(str(os).lower())
    if v not in (0, 1):
        raise ValueError("host os must be 'windows' or 'mac' (0 or 1)")
    return bytes([v])


def _partition_byte(opts: dict) -> bytes:
    # FORMAT_PARTITION targets one partition. The selector is INFERRED (a single index byte);
    # confirm against a capture before enabling. Default 0 if not given.
    return bytes([int(opts.get("partition", 0)) & 0xFF])


# SYS_MODULE_BATTERY_RECOVERY's one payload byte. NayaCore's _constructSystemMessages rejects an
# empty payload and anything but 00/01 ("0x00=OFF, 0x01=ON", initializeModuleTestValues), so the
# state is required, never defaulted. NayaFlow exposes the same thing as the key action "Activate
# Module Recovery Mode" (MODULE_FORCE_CHARGING); restarting the keyboard also turns it off.
def _on_off_byte(opts: dict) -> bytes:
    on = opts.get("on")
    if isinstance(on, str):
        on = {"on": True, "1": True, "true": True, "off": False, "0": False, "false": False}.get(on.lower())
    if not isinstance(on, bool):
        raise ValueError("battery recovery needs on: true or false (the firmware takes 01 or 00)")
    return b"\x01" if on else b"\x00"


# MODULE_FWUP's one payload byte, by the type the dock address decodes to. Only values PROVEN
# from NayaCore belong here, never a guess:
#   Touch = 01  on the wire: NayaFlow 1.25.1 update, 2026-09-23 (module-fw-touch1-20260923-part2.pcap)
#   Tune  = 02  on the wire: NayaFlow Force Update -> Tune, 2026-09-23 (module-fw-tune-nayaflow-force-*)
#   Track = 03  on the wire: NayaFlow Force Update -> Track, 2026-09-23 (module-fw-track-nayaflow-
#               recover-20260923.pcap), and a Track downgrade that read back as a Track; first read
#               from NayaCore's code: Naya_DeviceManager::doUpdateModuleOperations (NayaCore 6.11.0,
#               mac x86_64, symbols intact) builds the payload as QByteArray(1, N) in each forced
#               branch -- ModuleFW_Touch_Upload N=1, ModuleFW_Tune_Upload N=2,
#               ModuleFW_Track_Upload N=3. Touch and Tune match their captures exactly, which is
#               what makes the Track's value from the same code trustworthy. (NayaFlow will not
#               Force Update a module it recognises, so the Track's byte could not be captured.)
# nayactl's MODULE_TYPES (1 Touch, 2 Track, 3 Tune) is NOT this numbering. It was used as a guess
# for the Tune on 2026-09-23: OpenFlow sent 03, the keyboard gave the Tune the TRACK app, and it
# came back dark reporting dock address 0x4A until NayaFlow's forced 02 restored it.
FWUP_TYPES = {"Touch": 1, "Tune": 2, "Track": 3}


def _module_type_byte(opts: dict) -> bytes:
    # MODULE_FWUP: NayaCore validates "parameter size should be 1" and substitutes AUTO_DETECT for
    # an "invalid module_type", so the byte is a module type: FWUP_TYPES above, captured values
    # only. The supervised update is device/module_procedure.py; this op is the bare command.
    m = opts.get("module")
    mapping = {k.lower(): v for k, v in FWUP_TYPES.items()}
    v = mapping.get(str(m).lower())
    if v is None:
        raise ValueError(f"module must be one of {sorted(mapping)}: the type docked on this half, "
                         "as read from its address.")
    return bytes([v])


REGISTRY: tuple[RecoveryOp, ...] = (
    # --- resets: the mild recovery steps ------------------------------------------------------- #
    RecoveryOp("reset_normal", "Restart Keyboard", "Reboot the keyboard normally.",
               "reset", C.CAT_RESET, C.RESET_NORMAL, CONFIRMED,
               "Restart the keyboard now?"),
    RecoveryOp("reset_mcuboot", "Restart into Bootloader (MCUboot)",
               "Reboot into the MCUboot bootloader (for firmware recovery). Exits on a power cycle.",
               "reset", C.CAT_RESET, C.RESET_MCU_BOOT, CONFIRMED,
               "Restart the keyboard into its MCUboot bootloader? It will stop working as a keyboard "
               "until it is restarted again."),
    RecoveryOp("reset_dfu", "Restart into DFU",
               "Reboot into DFU mode (nRF firmware recovery). Exits on a power cycle.",
               "reset", C.CAT_RESET, C.RESET_DFU, CONFIRMED,
               "Restart the keyboard into DFU mode? It will stop working as a keyboard until it is "
               "restarted again."),
    RecoveryOp("reset_module", "Reset Docked Module",
               "Soft-reset the docked module (Touch / Track / Tune).",
               "reset", C.CAT_MODULE, C.MOD_RESET, INFERRED,
               "Reset the docked module now?"),

    # --- host OS -------------------------------------------------------------------------------- #
    RecoveryOp("set_host_os", "Set Host OS",
               "Tell the keyboard which OS it is plugged into (affects its own key handling).",
               "reset", C.CAT_SYSTEM, C.SYS_SET_HOST_OS, CONFIRMED,
               "Set the keyboard's host OS? This changes how the keyboard behaves.",
               args=("os",), build_payload=_host_os_byte),

    # --- module firmware: the app-mode half of the module flash (work-queue step 2) ------------ #
    # NayaCore's UpdateModule sequence is: upload FlashMemory.bin into the modules slot while the
    # LEFT half sits in MCUboot (flash_module_bundle in the gated upload module), reboot, then send
    # MODULE_FWUP with the docked module's type so the Create programs that module from its own
    # store, then compare GET_MODULE_FW_VERSION against the bundle's VERSION. This op is that
    # third step. It writes the MODULE, not the keyboard; it still ships disabled because the byte
    # value is inferred and because it has never been watched succeed.
    RecoveryOp("module_fwup", "Program Docked Module Firmware",
               "Tell the keyboard to program the docked module from the module firmware it holds "
               "(after a module bundle has been uploaded to it).",
               "recovery", C.CAT_MODULE, C.MOD_FWUP, INFERRED,
               "Program the docked module's firmware from the bundle stored on the keyboard? Keep "
               "the module docked until it reports its new version.",
               args=("module",), build_payload=_module_type_byte,
               needs="donor unit with a module docked, after the bundle upload is verified"),

    # --- module battery rescue ------------------------------------------------------------------ #
    RecoveryOp("module_battery_recovery", "Recover Module Battery",
               "The dead-module rescue for a module whose battery is critically drained.",
               "recovery", C.CAT_SYSTEM, C.SYS_MODULE_BATTERY_RECOVERY, INFERRED,
               "Run module battery recovery? Use this only for a module that will not charge.",
               args=("on",), build_payload=_on_off_byte),

    # --- pairing repair (the sharpest gap) ------------------------------------------------------ #
    RecoveryOp("ble_set_pair_address", "Set Split-Link Address",
               "Store the partner half's BLE address (step of re-pairing the two halves).",
               "recovery", C.CAT_BLE, C.BLE_SET_PAIR_ADDRESS, CONFIRMED,
               "Write the split-link partner address to this half?",
               args=("mac",), build_payload=_mac_bytes),
    RecoveryOp("ble_unpair_address", "Unpair One Address",
               "Forget one paired BLE address.",
               "recovery", C.CAT_BLE, C.BLE_UNPAIR_ADDRESS, CONFIRMED,
               "Forget this paired address?",
               args=("mac",), build_payload=_mac_bytes),
    RecoveryOp("ble_unpair_all", "Unpair All",
               "Forget every paired BLE address on this half.",
               "recovery", C.CAT_BLE, C.BLE_UNPAIR_ALL, INFERRED,
               "Forget ALL paired addresses on this half? The halves will need re-pairing."),
    RecoveryOp("ble_clear_all_split_links", "Clear All Split Links",
               "Clear the split-link state between the two halves (part of re-pairing).",
               "recovery", C.CAT_BLE, C.BLE_CLEAR_ALL_SPLIT_LINKS, INFERRED,
               "Clear the split link between the halves? They will need re-pairing afterwards."),

    # --- destructive: flash + data -------------------------------------------------------------- #
    RecoveryOp("clear_all_data", "Clear All Keymap Data",
               "Wipe every on-device keymap (REMAP clear).",
               "destructive", C.CAT_REMAP, R.CLEAR_ALL_DATA, INFERRED,
               "Wipe ALL keymap data on the keyboard? This cannot be undone."),
    RecoveryOp("format_partition", "Reformat Flash Partition",
               "Reformat a corrupt SPI-flash partition (the destructive half of the flash repair).",
               "destructive", C.CAT_FLASH, C.FLASH_FORMAT_PARTITION, INFERRED,
               "Reformat a flash partition? Data on it is erased; only for a flash that fails its "
               "self-test.", args=("partition",), build_payload=_partition_byte),
    RecoveryOp("erase_chip", "Erase Flash Chip",
               "Erase the entire external SPI-flash chip (the most destructive step).",
               "destructive", C.CAT_FLASH, C.FLASH_ERASE_CHIP, INFERRED,
               "ERASE the entire flash chip? This wipes firmware staging and all on-device data and "
               "cannot be undone."),
)

BY_ID = {op.id: op for op in REGISTRY}

# Individual ops may be enabled for ONE SESSION by naming them:
#
#     OPENFLOW_ENABLE_RECOVERY_OPS=ble_set_pair_address,ble_unpair_all
#
# A LIST, deliberately, not a boolean. These ops sit in one registry with erase_chip and
# format_partition, and "enable recovery ops" as a single switch would arm those too. Each one
# has to be named by whoever is running the session, and nothing is enabled by default.
#
# Set at import from the environment, so it cannot be committed on the way an edited
# `enabled=True` can.
# RecoveryOp is frozen, so an enabled copy replaces the entry rather than being mutated in
# place: REGISTRY keeps the shipped definitions, and only the lookup a caller goes through is
# swapped. dataclasses.replace also means a typo in the field name is an error, not a silent
# no-op the way setattr on a non-frozen class would be.
import dataclasses as _dc

for _name in (os.environ.get("OPENFLOW_ENABLE_RECOVERY_OPS") or "").split(","):
    _name = _name.strip()
    if _name and _name in BY_ID:
        BY_ID[_name] = _dc.replace(BY_ID[_name], enabled=True)


def public_list() -> list[dict]:
    """Registry for the UI: what each op is, its danger, whether it is enabled, its confirm text.
    No frames, no device access.

    Read through BY_ID, in REGISTRY's order: REGISTRY keeps the shipped definitions, and an op
    unlocked for the session exists only in BY_ID -- which is what the send path checks. Reading
    REGISTRY here listed an unlocked op as disabled while it would in fact run."""
    return [
        {"id": o.id, "label": o.label, "desc": o.desc, "danger": o.danger,
         "provenance": o.provenance, "enabled": o.enabled, "confirm": o.confirm,
         "args": list(o.args), "needs": o.needs,
         "command": f"{C.CATEGORY_NAMES.get(o.cat, hex(o.cat)) if hasattr(C, 'CATEGORY_NAMES') else hex(o.cat)}/{o.sub:#06x}"}
        for o in (BY_ID[r.id] for r in REGISTRY)
    ]


def frame_for(op_id: str, opts: dict | None = None) -> tuple[int, int, bytes]:
    """(category, subcommand, payload) for an op -- the exact bytes it would send. Pure; no device.
    This is what the tests pin, so a wrong opcode or payload shape is caught offline."""
    op = BY_ID.get(op_id)
    if op is None:
        raise ValueError(f"unknown recovery op: {op_id}")
    return op.cat, op.sub, op.payload(opts or {})
