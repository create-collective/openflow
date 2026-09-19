"""REST routes reimplementing NayaFlow's flow-bg-server contract.

Route names and shapes are taken from the recovered renderer
(extracted/NayaFlow-1.25.1/.../index-mihUmo_8.js). See docs/api-contract.md.
Not every original route is implemented in Phase 1 — the device-facing and
user-data routes are, and firmware/pairing routes return an explicit
not-implemented status rather than 404 so the UI can surface state cleanly.
"""

from __future__ import annotations

import logging
import sqlite3
import json
import io

import platform
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import __version__
from ..config import instance_token, is_frozen, reference_dir
from ..db import backup as bak
from ..db import keymap_import as kmi
from ..db import macros as mac
from ..db import device_state as dstate
from ..db import module_profiles as mprof
from ..db import profiles as prof
from ..db import settings as settings_db
from .. import report
from ..db import userdata as ud
from ..db.database import connect as db_connect
from ..device import (actions_catalog, flash as flash_mod, gesture_presets, keymap_read, module_fields,
                      module_layout, remap)
from ..device.commands import CommandError, dispatch
from ..device import recovery as recovery_mod
from ..device.service import DangerousCommandError, TransportError, pairing_report
from .state import get_service

log = logging.getLogger("openflow.api")

router = APIRouter()


# --- /api (GET) ------------------------------------------------------------

# The firmware NayaFlow 1.25.1 ships, so the UI can say "your half runs X, Naya ships Y".
# These are version NUMBERS, not vendor content -- the images themselves live in a gitignored
# tree and the backend deliberately does not read it, so nothing here depends on that tree
# being present. Update when a newer NayaFlow is examined.
REFERENCE_FIRMWARE = {
    "source": "NayaFlow 1.25.1 (NayaCore v6.11.0)",
    "createFirmware": "3.41.0",
    "moduleFirmware": "2.3.3",
}


@router.get("/api/info/system")
async def info_system() -> dict:
    return {
        "app": "OpenFlow",
        "backendVersion": __version__,
        "os": platform.system(),
        "osVersion": platform.version(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "reference": REFERENCE_FIRMWARE,
        # The desktop shell launched us with a per-launch token; it accepts only a backend that
        # echoes its own. None when started by hand.
        "instance": instance_token(),
        "frozen": is_frozen(),
    }


@router.post("/rpc/shutdown")
async def shutdown(request: Request, body: dict = Body(default={})) -> dict:
    """Stop the server cleanly: the lifespan shutdown closes the keyboard's port and stops the
    poll loop, which a killed process does not do. Offered only to whoever launched us with
    OPENFLOW_INSTANCE (the desktop shell, the sidecar smoke test) and only with that token."""
    token = instance_token()
    if not token or body.get("instance") != token:
        raise HTTPException(status_code=403, detail="shutdown needs this backend's instance token")
    server = getattr(request.app.state, "server", None)
    if server is None:
        raise HTTPException(status_code=503,
                            detail="no server handle to stop (not started by openflow_backend.__main__)")
    server.should_exit = True
    return {"status": "stopping"}


def _catalog_json() -> dict:
    """docs/reference/firmware-catalog.json via config.reference_dir(): the committed catalogue
    metadata (versions + hashes, NOT the gitignored image tree). {} when absent or unreadable."""
    d = reference_dir()
    cand = d / "firmware-catalog.json" if d else None
    if cand is None or not cand.is_file():
        return {}
    try:
        return json.loads(cand.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _firmware_catalog_raw() -> list[dict]:
    """The catalogue entries verbatim -- the shape firmware_upload.plan() checks (`side`,
    `generation`, full `plaintextSha256`, `withheldBecause`). _firmware_catalog() below is the UI
    summary and must NOT be handed to the flasher: it drops `side` and truncates the hash, which
    would make every image fail the side check."""
    return _catalog_json().get("images", [])


def _firmware_catalog() -> list[dict]:
    """The bundled firmware images, summarised for the Software page. [] when the catalogue is
    not present."""
    out = []
    for img in _catalog_json().get("images", []):
        version = img.get("createFirmware") or img.get("moduleFirmware")
        out.append({
            "file": img.get("file"),
            "target": img.get("target"),                    # keyboard | module
            "component": img.get("component"),              # left/right, modules, touch/track/tune, dial
            "container": img.get("container"),              # the .sfb userapps sit inside FlashMemory.bin
            "generation": img.get("generation"),           # A/B flash generation (keyboard)
            "version": version,
            "versionConfidence": img.get("versionConfidence"),
            # The version number when a release declared one, else the NayaFlow release
            # span that shipped the image ("NayaFlow 1.3.8 to 1.6.10"). The UI groups by it.
            "versionLabel": img.get("versionLabel") or version,
            "bundle": img.get("bundle") or img.get("source"),
            "bundles": img.get("bundles") or ([img["bundle"]] if img.get("bundle") else []),
            "firstSeen": img.get("firstSeen"),
            "lastSeen": img.get("lastSeen"),
            "releaseOrder": img.get("releaseOrder"),       # chronological; newest first in the UI
            "era": img.get("era"),
            "historyPath": img.get("historyPath"),         # where it sits in nayaHistory/firmware-history
            "flashable": img.get("flashable", False),
            "withheldBecause": img.get("withheldBecause") or [],
            "note": img.get("note"),
            # keyboard: the MCUboot plaintext hash; bundle: its blob; userapp: the
            # bundle's own _HASH sidecar for it
            "sha256": (img.get("plaintextSha256") or img.get("blobSha256")
                       or img.get("sha256") or "")[:16],
        })
    return out


def _firmware_releases() -> list[dict]:
    """The NayaFlow release list the catalogue was built from: tag, date, order, and the Create /
    module firmware version each release declared (None where it declared nothing)."""
    return _catalog_json().get("releases", [])


@router.get("/api/device-log")
async def device_log(limit: int = 200) -> dict:
    """Recent device I/O -- every command/text/raw exchange with a connected keyboard, newest last.
    In-memory for the quick view; also appended to a daily file under the logs folder (kept
    RETENTION_DAYS). Device bytes only, nothing user-identifying."""
    from ..device import device_log as dl
    from ..config import logs_dir
    return {"entries": dl.entries(limit), "dir": str(logs_dir()),
            "retentionDays": dl.RETENTION_DAYS}


@router.post("/rpc/clear-device-log")
async def clear_device_log() -> dict:
    from ..device import device_log as dl
    dl.clear()
    return {"ok": True}


@router.post("/rpc/open-logs-folder")
async def open_logs_folder(body: dict = Body(default={})) -> dict:
    import os
    import subprocess
    import sys
    from ..config import logs_dir
    d = logs_dir()
    if sys.platform == "win32":
        os.startfile(str(d))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)])
    return {"ok": True, "dir": str(d)}


# Firmware flashing is wired but GATED at the module level, exactly like the recovery ops: even
# with an arm token and force, the endpoint refuses while this is False, so it ships visible-but-
# inert until it is tested on a donor unit. Flip to True (per target) only after that test.
FIRMWARE_FLASH_ENABLED = False


@router.post("/rpc/flash-firmware")
async def flash_firmware(body: dict = Body(...)) -> dict:
    """Flash a catalogued firmware image. WIRED BUT DISABLED until tested on a donor unit -- refuses
    here before touching the interlocked upload path (device/firmware_upload.py), which itself
    requires an arm token equal to the hash the device just reported. Two gates, neither bypassable
    from the UI."""
    if not FIRMWARE_FLASH_ENABLED:
        raise HTTPException(status_code=400, detail=(
            "Firmware flashing is wired but disabled until it is verified on a donor unit. "
            "Nothing was sent."))
    import os
    from pathlib import Path as _P
    from ..device import firmware_upload as fw
    try:
        name = str(body["image"])
        path = _P(name)
        if not path.is_absolute():
            # The images are vendor material and live outside the repo; OPENFLOW_FIRMWARE_DIR
            # says where. A bare catalogue filename with no dir set fails plan()'s "no such
            # image" check.
            d = os.environ.get("OPENFLOW_FIRMWARE_DIR")
            path = _P(d) / name if d else path
        # flash() = upload -> re-read slot -> schedule the swap -> reset. Default confirm=False
        # is a TEST swap (boots once, reverts unless the app confirms itself); confirm=True is
        # permanent. vendor_trailer=True uploads the whole resource as NayaCore does, which arms
        # a permanent swap by itself. See firmware_upload.py's note.
        return await run_in_threadpool(
            fw.flash, path, _firmware_catalog_raw(), arm=body.get("arm", ""),
            slot=int(body.get("slot", 1)), allow_older=bool(body.get("allow_older", False)),
            confirm=bool(body.get("confirm", False)),
            vendor_trailer=bool(body.get("vendor_trailer", False)))
    except (fw.UploadRefused, TransportError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/flash-module-firmware")
async def flash_module_firmware(body: dict = Body(...)) -> dict:
    """Upload a catalogued module bundle (FlashMemory.bin) into the left half's modules slot and
    reboot it. Same two gates as the keyboard flash: refused here while FIRMWARE_FLASH_ENABLED is
    False, and the upload path itself needs `arm` = the hash the half reports for its running
    image. A third stands in front of both: the bundle's catalogue entry is withheld until the
    modules slot is confirmed on a donor unit (build_firmware_catalog.MODULE_PATH_WITHHELD)."""
    if not FIRMWARE_FLASH_ENABLED:
        raise HTTPException(status_code=400, detail=(
            "Firmware flashing is wired but disabled until it is verified on a donor unit. "
            "Nothing was sent."))
    import os
    from pathlib import Path as _P
    from ..device import firmware_upload as fw
    try:
        name = str(body["image"])
        path = _P(name)
        if not path.is_absolute():
            d = os.environ.get("OPENFLOW_FIRMWARE_DIR")
            path = _P(d) / name if d else path
        return await run_in_threadpool(
            fw.flash_module_bundle, path, _firmware_catalog_raw(), arm=body.get("arm", ""),
            installed_version=body.get("installed_version"),
            allow_older=bool(body.get("allow_older", False)))
    except (fw.UploadRefused, TransportError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/recovery-read")
async def recovery_read() -> dict:
    """What a half sitting in MCUboot recovery is running, matched against the catalogue, plus the
    bootloader's slot map (`image slot info`) when it answers one. Reads only; opens the recovery
    port for two SMP reads and closes it. This is the read that pins how uploads are addressed
    (work-queue step 3): expect `slotInfo.slots[*].uploadImageId` and a 1048576-byte slot."""
    return await run_in_threadpool(recovery_mod.read_running_image, _firmware_catalog_raw())


@router.get("/api/module-firmware-file")
async def module_firmware_file(side: str = "left") -> dict:
    """The module firmware version the keyboard HOLDS in its modules slot (MODULE_FILE_FW_VERSION),
    as distinct from what a docked module runs. A read; the post-upload check for a bundle."""
    svc = get_service()
    try:
        return await run_in_threadpool(svc.module_file_fw_version, side)
    except (CommandError, TransportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/pairing-repair/plan")
async def pairing_repair_plan() -> dict:
    """The guided split-link repair, planned against a fresh deep read of both halves: what would
    be stored before anything is cleared, every step with its exact frame, the arm token, and a
    refusal instead when the halves are not in a state the sequence accepts. Reads only."""
    from ..device import pairing_repair as pr
    svc = get_service()
    halves = await run_in_threadpool(svc.status_all, True)
    try:
        return pr.plan(halves).public()
    except pr.PairingRefused as e:
        return {"refused": str(e), "enabled": pr.PAIRING_REPAIR_ENABLED}


@router.post("/rpc/pairing-repair")
async def pairing_repair_run(body: dict = Body(...)) -> dict:
    """Run the guided repair. WIRED BUT DISABLED (pairing_repair.PAIRING_REPAIR_ENABLED ships
    False) and, underneath, every op it sends is a disabled recovery op; `arm` must be the token
    of a plan made against the halves' current addresses, and `force` is required because the
    sequence drops every Bluetooth bond on both halves."""
    from ..device import pairing_repair as pr
    svc = get_service()
    halves = await run_in_threadpool(svc.status_all, True)
    try:
        p = pr.plan(halves)
        return await run_in_threadpool(pr.execute, svc, p, arm=body.get("arm", ""),
                                       force=bool(body.get("force", False)))
    except (pr.PairingRefused, CommandError, TransportError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/pairing-repair/verify")
async def pairing_repair_verify() -> dict:
    """The check that follows the repair (and works on its own): both halves read deep, each
    one's pair address compared with the other's own address, and the split link's state."""
    from ..device import pairing_repair as pr
    svc = get_service()
    halves = await run_in_threadpool(svc.status_all, True)
    return pr.verify(halves)


@router.get("/api/recovery-ops")
async def recovery_ops_list() -> dict:
    """The recovery/troubleshooting procedures for the UI: label, danger, whether enabled, and the
    confirmation text. No device access; the ops themselves are wired but gated (see recovery_ops)."""
    from ..device import recovery_ops as ro
    return {"ops": ro.public_list()}


@router.post("/rpc/run-recovery-op")
async def run_recovery_op(body: dict = Body(...)) -> dict:
    """Run one recovery op. Refuses a disabled op (all are, until donor-unit testing) and requires
    force. The frame is built and pinned by tests, so a disabled op cannot fire even by mistake."""
    svc = get_service()
    try:
        return await run_in_threadpool(
            svc.run_recovery_op, body.get("side", "left"), body["op"],
            body.get("opts") or {}, force=bool(body.get("force", False)))
    except (CommandError, TransportError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/firmware-catalog")
async def firmware_catalog() -> dict:
    """Firmware versions bundled/known to OpenFlow, for the Software page's firmware list: one
    entry per distinct image across every NayaFlow release, plus the release list itself."""
    return {"reference": REFERENCE_FIRMWARE, "images": _firmware_catalog(),
            "releases": _firmware_releases()}


@router.get("/api/ui/state")
async def ui_state() -> dict:
    svc = get_service()
    devices = await run_in_threadpool(svc.list_devices)
    return {"ready": True, "deviceCount": len(devices)}


@router.get("/api/devices")
async def devices() -> dict:
    svc = get_service()
    return {"devices": await run_in_threadpool(svc.list_devices),
            "ignored": svc.ignored_ports()}


@router.post("/rpc/ignore-port")
async def ignore_port(body: dict = Body(...)) -> dict:
    """Leave a port alone: no resolution, no poll, not on the Devices page.

    For the port a keyboard left behind when it re-enumerated. Windows keeps listing such a
    node and nothing we do removes it, so the most we can offer is to stop choosing it. Kept
    on disk, because those ghosts outlive an app restart.
    """
    port = (body.get("port") or "").strip()
    if not port:
        raise HTTPException(status_code=400, detail="which port?")
    return await run_in_threadpool(get_service().ignore_port, port)


@router.post("/rpc/unignore-port")
async def unignore_port(body: dict = Body(...)) -> dict:
    port = (body.get("port") or "").strip()
    if not port:
        raise HTTPException(status_code=400, detail="which port?")
    return await run_in_threadpool(get_service().unignore_port, port)


@router.get("/api/status")
async def status(verbose: bool = False) -> dict:
    """Query the halves over USB. Persists the result so the page can paint from cache next
    time rather than re-opening the port on every mount."""
    svc = get_service()
    halves = await run_in_threadpool(svc.status_all, verbose)
    # An empty reading (nothing answered: unplugged, or the port busy with a keymap read a
    # moment earlier) is not worth remembering over the last one that saw the keyboard. The
    # pages paint their bays and halves from this cache, and persisting a blank wiped them
    # on every load until the next good read.
    if halves:
        saved = await run_in_threadpool(dstate.save_status, halves, verbose)
        at = saved["at"]
    else:
        at = dstate.now_stamp()
    out = {"halves": halves, "at": at}
    # A half in MCUboot enumerates under a different product id and answers none of the normal
    # protocol, so without this it is not merely unidentified -- it does not appear at all, and
    # the page looks the same as if it were unplugged.
    stuck = recovery_mod.find_recovery_ports()
    if stuck:
        out["recovery"] = [{"port": d.port, "description": d.description, "pid": d.pid,
                            "side": d.side, "generation": d.generation} for d in stuck]
    # Only meaningful with the BLE block, which a plain read does not fetch.
    if verbose:
        out["pairing"] = pairing_report(halves)
    return out


def _cache_matches_attached(cached: dict):
    """Does a cached status describe the keyboard that is attached NOW?

    One of:
      True            a serial in the cache is on the bus now
      False           none is: this describes a DIFFERENT keyboard
      "disconnected"  nothing is on the bus at all
      None            cannot tell -- no serial on one side or the other, which is a real
                      state on older firmware and must not be reported as a mismatch

    Compared by SERIAL against USB enumeration. That needs no serial I/O, so the answer
    costs nothing and cannot disturb a port; asking the keyboard would defeat the point of
    a cache that exists to avoid exactly that.

    A PARTIAL overlap counts as matching: swapping one half leaves the other genuinely
    described, and calling that "a different keyboard" would be the more misleading answer.
    """
    have = {h.get("serialNumber") for h in (cached.get("halves") or [])}
    have.discard(None)
    if not have:
        return None
    try:
        now = {d.serial_number for d in get_service().visible_ports()}
    except Exception:
        return None                # enumeration failed: say nothing rather than guess
    now.discard(None)
    if not now:
        # Nothing on USB. The reading is not about a DIFFERENT keyboard, but it is about one
        # that is no longer here, and a page showing its ports and modules with no marker is
        # the same confusion in a quieter form. Reported as its own state so the page can say
        # which of the two it is.
        return "disconnected"
    return bool(have & now)


@router.get("/api/status/last")
async def status_last(deep: bool = False) -> dict:
    """The last half status we read, and when. Touches no hardware.

    Device Manager fired a fresh USB read on every mount, so navigating away and back asked the
    keyboard the same questions again -- even right after a read that had just told us. It now
    paints this immediately and says "as of", and re-reading is a deliberate click.
    """
    got = await run_in_threadpool(dstate.load_status, deep)
    got["released"] = get_service().released
    got["describesAttached"] = await run_in_threadpool(_cache_matches_attached, got)
    # Recomputed from the cached halves rather than persisted: it is derived, and storing a
    # derived verdict is how a stale one outlives the data it came from.
    if deep and got.get("halves"):
        got["pairing"] = pairing_report(got["halves"])
    return got


@router.post("/rpc/read-keyboard")
async def read_keyboard(body: dict = Body(default={})) -> dict:
    """Read the map currently on the keyboard and import it, matching an existing profile by
    layer uuid where one exists.

    The module config LIST is read too, so the per-layer module bays can be resolved from slot
    numbers to actual profiles. Without it the bays would be uninterpretable -- a bay holds a
    slot index, and only the list says which profile that slot is.
    """
    svc = get_service()
    side = body.get("side", "left")
    try:
        read = await run_in_threadpool(svc.read_keymap, side)
        slot_uuid, mod_read = {}, None
        try:
            mod_read = await run_in_threadpool(svc.read_module_configs, side)
            slot_uuid = {slot: uuid for uuid, slot in (mod_read.get("by_uuid") or {}).items()}
        except Exception:
            pass    # a keymap read is still worth having if the module list is unreadable
    except TransportError as e:
        raise HTTPException(status_code=503, detail=str(e))
    # Resolve (and capture) the board's module slots BEFORE the keymap import binds the bays.
    # Until 2026-09-16 the import ran first and recorded a bay only when the slot's uuid was
    # already a config id, and the capture came after -- so a slot the app knew only by content
    # (every NayaFlow-written slot, or one this very read captures) lost its bays, and layer 0
    # came back with no Touch profile at all (SCRUM-61). Now the bay binds to the config the
    # slot MATCHES, capture included, and the repoint below is only a safety net.
    diff, slot_cfg = None, slot_uuid
    if mod_read is not None:
        try:
            diff = await run_in_threadpool(_module_diff, mod_read, None)
            slot_cfg = _slot_config_map(diff["modules"], mod_read.get("by_uuid")) or slot_uuid
        except Exception:
            diff = None    # the keymap import is the payload that matters
    out = await run_in_threadpool(kmi.import_read, read, body.get("name"), slot_cfg)
    # Report which module profiles the board carries, so reading from the Bindings page
    # populates the same shared device state that reading from the Modules page does.
    if diff is not None:
        try:
            repointed = await run_in_threadpool(
                mprof.repoint_bays,
                [(e.get("uuid"), e.get("matched")) for e in diff["modules"]],
                out.get("profileId"))
            out.update({**diff, "repointedBays": repointed})
        except Exception:
            pass
    return out


def _slot_config_map(entries: list, by_uuid: dict | None) -> dict:
    """{device slot: app config id} for the keymap import to bind bays with: the config each
    slot MATCHES by content (a capture the same read just minted, or a stock profile a
    NayaFlow-written slot happens to equal), else the slot's own uuid for a slot whose uuid is
    itself an app config. A bay names a slot; this is what turns the slot into a profile."""
    slots = dict(by_uuid or {})
    out = {}
    for e in entries or []:
        u = e.get("uuid")
        if u in slots:
            out[slots[u]] = e.get("matched") or u
    return out


@router.get("/api/userdata")
async def userdata() -> dict:
    """Profiles -> layers -> keys -> bindings, from the offline SQLite store."""
    return await run_in_threadpool(ud.get_userdata)


@router.get("/api/modules")
async def modules() -> dict:
    """Module configs (Touch/Track/Tune) with gesture bindings + settings."""
    return await run_in_threadpool(ud.get_modules)


@router.post("/rpc/set-module-setting")
async def set_module_setting(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(
            ud.set_module_setting, body["configId"], body["fieldId"], body["value"]
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-module-binding")
async def set_module_binding(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(
            ud.set_module_binding, body["bindingId"], body.get("actionCode", ""), body.get("actionType", "none")
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/settings")
async def get_settings() -> dict:
    return await run_in_threadpool(settings_db.get_settings)


# LED settings that reach the device as a LIVE command (not on flash), verified on hardware
# 2026-09-13 (brightness, scan mode) and 2026-09-16 (layer override, SCRUM-24). Changing the
# setting saves it AND, if a keyboard is connected, sends it live -- which is what makes these
# actually take effect from the UI. The override's wire value is the option index: 0 = until
# keyboard restart, 1 = until next layer change; the stored value may be the label or the
# NayaFlow wire name (until_layer_change), so both spellings map.
_LED_LIVE_SETTINGS = {
    "led_max_brightness": ("max_brightness", lambda v: int(v)),
    "led_scan_mode": ("scan_mode", lambda v: 1 if v in (True, 1, "true", "True") else 0),
    "led_action_override": ("layer_override", lambda v: 1 if "layer" in str(v).lower() else 0),
}


@router.post("/rpc/set-setting")
async def set_setting(body: dict = Body(...)) -> dict:
    key, value = body["key"], body["value"]
    try:
        result = await run_in_threadpool(settings_db.set_setting, key, value)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Apply live if this is a device-live LED setting and a keyboard is connected. Best-effort:
    # the setting is already saved, so a device that is absent or errors does not fail the save --
    # it is reported so the UI can say "saved, not applied (no device)".
    live = _LED_LIVE_SETTINGS.get(key)
    if live:
        setting, to_int = live
        svc = get_service()
        try:
            devices = await run_in_threadpool(svc.list_devices)
            if devices:
                await run_in_threadpool(svc.led_setting, "left", setting, to_int(value))
                result["applied"] = True
            else:
                result["applied"] = False
                result["applyNote"] = "saved; no keyboard connected to apply it live"
        except (TransportError, ValueError) as e:
            result["applied"] = False
            result["applyNote"] = f"saved, but applying to the device failed: {e}"
    return result


@router.get("/api/backups")
async def backups() -> dict:
    return await run_in_threadpool(bak.list_backups)


@router.post("/rpc/open-backup-folder")
async def open_backup_folder(body: dict = Body(default={})) -> dict:
    try:
        return await run_in_threadpool(bak.open_dir)
    except Exception as e:  # noqa: BLE001 - surface any OS error to the UI
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/create-backup")
async def create_backup(body: dict = Body(default={})) -> dict:
    try:
        return await run_in_threadpool(bak.create_backup, "manual")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/restore-backup")
async def restore_backup(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(bak.restore_backup, body["name"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/import-profile-file")
async def import_profile_file(file: UploadFile = File(...)) -> dict:
    """"Load profile from file": an OpenFlow profile export (.json), a NayaFlow user-data.db,
    or a NayaFlow backup .zip that bundles one. A database is converted in a throwaway copy
    (db.nayaflow_convert) and each profile it holds is imported as a NEW profile beside the
    user's own -- nothing installs over the current data, unlike /rpc/import-backup-file."""
    import tempfile
    import zipfile
    from ..db import nayaflow_convert as ncv

    raw = await file.read()
    name = (file.filename or "upload").lower()

    def _go() -> dict:
        if name.endswith(".json"):
            data = json.loads(raw.decode("utf-8"))
            r = prof.import_profile(data)
            return {"ok": True, "source": "json", "imported": [{"id": r["id"], "name": r["name"]}]}
        db_bytes = raw
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                member = next((n for n in zf.namelist() if n.lower().endswith(".db")), None)
                if member is None:
                    raise ValueError("the zip holds no .db file")
                db_bytes = zf.read(member)
        elif not name.endswith(".db"):
            raise ValueError("expected a .json profile export, a NayaFlow user-data.db, or its backup .zip")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "upload.db"
            tmp.write_bytes(db_bytes)
            payloads = ncv.to_json_payloads(tmp)
        if not payloads:
            raise ValueError("that database holds no profiles")
        imported = []
        for payload in payloads:
            r = prof.import_profile(payload)
            imported.append({"id": r["id"], "name": r["name"]})
        return {"ok": True, "source": "nayaflow-db", "imported": imported}

    try:
        return await run_in_threadpool(_go)
    except (ValueError, KeyError, sqlite3.DatabaseError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/convert-db-to-json")
async def convert_db_to_json(file: UploadFile = File(...)) -> dict:
    """Convert a NayaFlow user-data.db (or its backup .zip) to OpenFlow profile JSON, WITHOUT
    importing anything. The other half of backup portability: "Load profile from file" already
    imports a .db, this hands back the JSON so a .db backup can be kept, shared or diffed as text.
    Reads a throwaway copy; nothing on disk or in the live database is touched."""
    import tempfile
    import zipfile
    from ..db import nayaflow_convert as ncv

    raw = await file.read()
    name = (file.filename or "upload").lower()

    def _go() -> dict:
        db_bytes = raw
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                member = next((n for n in zf.namelist() if n.lower().endswith(".db")), None)
                if member is None:
                    raise ValueError("the zip holds no .db file")
                db_bytes = zf.read(member)
        elif not name.endswith(".db"):
            raise ValueError("expected a NayaFlow user-data.db or its backup .zip")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "upload.db"
            tmp.write_bytes(db_bytes)
            payloads = ncv.to_json_payloads(tmp)
        if not payloads:
            raise ValueError("that database holds no profiles")
        return {"ok": True, "profiles": payloads}

    try:
        return await run_in_threadpool(_go)
    except (ValueError, KeyError, sqlite3.DatabaseError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/import-backup-file")
async def import_backup_file(file: UploadFile = File(...)) -> dict:
    """Install an uploaded .db or NayaFlow backup .zip as the current data."""
    raw = await file.read()
    try:
        return await run_in_threadpool(bak.import_db_bytes, raw, file.filename or "upload.db")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/actions")
async def actions() -> dict:
    """The action palette: categorized action codes, behavior slots, layer types."""
    return actions_catalog.get_catalog()


@router.get("/api/macros")
async def macros() -> dict:
    return await run_in_threadpool(mac.get_macros)


@router.post("/rpc/create-macro")
async def create_macro(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(mac.create_macro, body["name"])
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/delete-macro")
async def delete_macro(body: dict = Body(...)) -> dict:
    return await run_in_threadpool(mac.delete_macro, body["id"])


@router.post("/rpc/add-macro-step")
async def add_macro_step(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(
            mac.add_step, body["macroId"], body["kind"],
            action_code=body.get("actionCode"), state=body.get("state", "tap"),
            input=body.get("input", ""), delay=int(body.get("delay", 30)),
            program=body.get("program", ""), args=body.get("args") or [],
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/add-macro-steps")
async def add_macro_steps(body: dict = Body(...)) -> dict:
    """Append several steps at once -- what the recorder produces.

    One call rather than one per keystroke: a recording is a unit, and adding it key by key
    would leave a half-recorded macro behind if the page navigated mid-flight.
    """
    macro_id = body.get("macroId")
    steps = body.get("steps") or []
    if not macro_id or not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="macroId and steps[] are required")
    added = []
    try:
        for st in steps:
            r = await run_in_threadpool(
                mac.add_step, macro_id, st.get("kind", "key"),
                action_code=st.get("actionCode"), state=st.get("state", "tap"),
                input=st.get("input", ""), delay=int(st.get("delay", 30)),
                program=st.get("program", ""), args=st.get("args") or [])
            added.append(r["id"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "added": added}


@router.post("/rpc/delete-macro-step")
async def delete_macro_step(body: dict = Body(...)) -> dict:
    return await run_in_threadpool(mac.delete_step, body["stepId"])


@router.post("/rpc/reorder-macro-steps")
async def reorder_macro_steps(body: dict = Body(...)) -> dict:
    return await run_in_threadpool(mac.reorder_steps, body["macroId"], body["orderedIds"])


@router.post("/rpc/rename-macro")
async def rename_macro(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(mac.rename_macro, body["macroId"], body.get("name", ""))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/update-macro-step")
async def update_macro_step(body: dict = Body(...)) -> dict:
    """Edit a step in place. Previously the delay could only be chosen when the step was
    created, so correcting a timing meant deleting and rebuilding it -- losing its position."""
    try:
        return await run_in_threadpool(
            mac.update_step, body["stepId"],
            delay=body.get("delay"), action_code=body.get("actionCode"),
            state=body.get("state"), input=body.get("input"),
            program=body.get("program"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-key-binding")
async def set_key_binding(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(
            ud.set_key_binding,
            body["layerId"],
            int(body["positionId"]),
            body["actionCode"],
            body["actionType"],
            body.get("behavior", "tap"),
            body.get("context"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/clear-key-binding")
async def clear_key_binding(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(
            ud.clear_key_binding, body["layerId"], int(body["positionId"]), body.get("behavior")
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-key-color")
async def set_key_color(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(
            ud.set_key_color, body["layerId"], int(body["positionId"]), body.get("colorHex")
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/fill-layer-color")
async def fill_layer_color(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.fill_layer_color, body["layerId"], body.get("colorHex"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-layer-animation")
async def set_layer_animation(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.set_layer_animation, body["layerId"], body.get("animation"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-module-led")
async def set_module_led(body: dict = Body(...)) -> dict:
    """Colour for a docked module's LED block on one layer. See db.userdata.set_module_led."""
    try:
        return await run_in_threadpool(ud.set_module_led, body["layerId"], body["side"],
                                       body.get("colorHex"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/create-profile")
async def create_profile(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(prof.create_profile, body.get("name", "New Profile"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/rename-profile")
async def rename_profile(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(prof.rename_profile, body["profileId"], body["name"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/duplicate-profile")
async def duplicate_profile(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(prof.duplicate_profile, body["profileId"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/delete-profile")
async def delete_profile(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(prof.delete_profile, body["profileId"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/export-profile")
async def export_profile(profileId: str) -> dict:
    try:
        return await run_in_threadpool(prof.export_profile, profileId)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/import-profile")
async def import_profile(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(prof.import_profile, body["data"], body.get("name"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/export-layer")
async def export_layer(layerId: str) -> dict:
    try:
        return await run_in_threadpool(prof.export_layer, layerId)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/copy-layer")
async def copy_layer(body: dict = Body(...)) -> dict:
    """Copy a layer from any profile into another, without going through a file.

    Layer import/export has only ever worked through the file browser, which makes "take the
    layer I just read off the keyboard and put it in my own profile" a save-then-load chore for
    something entirely internal.
    """
    try:
        return await run_in_threadpool(prof.copy_layer, body["layerId"], body["profileId"],
                                       body.get("name"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/import-layer")
async def import_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(prof.import_layer, body["profileId"], body["data"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/create-layer")
async def create_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.create_layer, body["profileId"], body.get("name", "New Layer"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/rename-layer")
async def rename_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.rename_layer, body["layerId"], body["name"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/layer-references")
async def layer_references(layerId: str) -> dict:
    """How many keys switch TO this layer -- for the delete confirmation, before anything goes.

    They cannot be repointed automatically: there is no correct answer to "which layer did you
    mean instead", and guessing would silently change what the keyboard does. So the user is
    told the count and the bindings are cleared on delete.
    """
    try:
        return await run_in_threadpool(ud.layer_reference_count, layerId)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/delete-layer")
async def delete_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.delete_layer, body["layerId"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/duplicate-layer")
async def duplicate_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.duplicate_layer, body["layerId"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/reorder-layers")
async def reorder_layers(body: dict = Body(...)) -> dict:
    """Reorder a profile's layers. Takes the complete ordered id list, not a move."""
    try:
        return await run_in_threadpool(ud.reorder_layers, body["profileId"], body["orderedIds"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-base-layer")
async def set_base_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.set_base_layer, body["layerId"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/release-device")
async def release_device() -> dict:
    """Close the serial ports and stand the poll down, so NayaFlow (or anything else) can use
    the keyboard without OpenFlow being quit. Nothing on the device changes."""
    return await run_in_threadpool(get_service().release)


@router.post("/rpc/reconnect-device")
async def reconnect_device() -> dict:
    """Take the keyboard back; the next poll tick reopens it."""
    return await run_in_threadpool(get_service().reconnect)


@router.get("/api/report/context")
async def report_context(identifiers: bool = False) -> dict:
    """What an in-app report would carry about this machine, so the page can show it BEFORE
    anything is sent. `identifiers=false` (the default) strips hardware IDs, BLE addresses and
    serial numbers: a report goes to a tracker, and those name a particular unit."""
    from ..device import device_log as dl
    svc = get_service()
    last = await run_in_threadpool(dstate.load_status, False)
    ctx = await run_in_threadpool(report.collect_context, svc, dl.entries(40), last)
    cfg = report.jira_config()
    ctx["sink"] = None if cfg is None else ("webhook" if cfg.get("webhook") else "jira")
    return ctx if identifiers else report.redact(ctx)


@router.post("/rpc/report-bug")
async def report_bug(body: dict = Body(...)) -> dict:
    """File a user's report. Returns the rendered text either way, so a build with no sink
    configured can still offer it to be copied or saved."""
    if not (body.get("happened") or "").strip():
        raise HTTPException(status_code=400, detail="say what happened before sending a report")
    from ..device import device_log as dl
    svc = get_service()
    last = await run_in_threadpool(dstate.load_status, False)
    ctx = await run_in_threadpool(report.collect_context, svc, dl.entries(40), last)
    if not body.get("includeIdentifiers"):
        ctx = report.redact(ctx)
    return await run_in_threadpool(report.file_report, svc, body, ctx)


@router.get("/api/diagnostics/report")
async def diagnostics_report() -> dict:
    svc = get_service()
    devices = await run_in_threadpool(svc.list_devices)
    halves = await run_in_threadpool(svc.status_all)
    return {
        "generatedBy": f"OpenFlow {__version__}",
        "os": platform.platform(),
        "devices": devices,
        "halves": halves,
    }


# --- /rpc (POST) -----------------------------------------------------------

@router.post("/rpc/send-nayacore-zmq-message")
async def send_zmq_message(body: dict = Body(...)) -> dict:
    """The original single device-control entry point.

    Body: { messages: [topic, event, ...frames] }
    """
    messages = body.get("messages") or []
    if len(messages) < 2:
        raise HTTPException(status_code=400, detail="messages must be [topic, event, ...frames]")
    _topic, event, *frames = messages
    side = body.get("side", "left")
    force = bool(body.get("force", False))
    svc = get_service()
    try:
        result = await run_in_threadpool(dispatch, svc, event, frames, side=side, force=force)
        return {"ok": True, "result": result}
    except (CommandError, DangerousCommandError, TransportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/led")
async def led(body: dict = Body(...)) -> dict:
    svc = get_service()
    try:
        return await run_in_threadpool(
            svc.led, body.get("side", "left"), body["action"], body.get("value")
        )
    except (TransportError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/led-setting")
async def led_setting(body: dict = Body(...)) -> dict:
    """Send a persistent LED setting live (scan_mode / max_brightness / layer_override). The
    testing surface these were verified through (2026-09-13, 2026-09-16); /rpc/set-setting is the
    everyday path. max_brightness=0 is refused (dark-board)."""
    svc = get_service()
    try:
        return await run_in_threadpool(
            svc.led_setting, body.get("side", "left"), body["setting"], body["value"]
        )
    except (TransportError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/status/live")
async def status_live() -> dict:
    """What the poll loop last saw: per half, connection, battery, docked module. No device I/O."""
    return get_service().snapshot()


@router.get("/api/ble/profiles")
async def ble_profiles(side: str = "left") -> dict:
    """The five Bluetooth slots: active, bonded, reserved. One status read."""
    svc = get_service()
    try:
        return await run_in_threadpool(svc.ble_profiles, side)
    except (TransportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/select-ble-profile")
async def select_ble_profile(body: dict = Body(...)) -> dict:
    """Switch the keyboard's active Bluetooth slot -- the same as pressing BT n on it, so typing
    moves to that slot's host. Gated like every other write to the keyboard."""
    if body.get("confirm") != "SELECT":
        raise HTTPException(status_code=400,
                            detail='refusing: this changes which Bluetooth slot the keyboard uses, '
                                   'the same as pressing BT n on it. Send {"confirm": "SELECT"}.')
    svc = get_service()
    try:
        return await run_in_threadpool(svc.select_ble_profile, body.get("side", "left"),
                                       body.get("index"), bool(body.get("allowReserved")))
    except (TransportError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/clear-ble-profile")
async def clear_ble_profile(body: dict = Body(...)) -> dict:
    """Drop a slot's bond and start pairing for it. Destructive; needs its own token."""
    if body.get("confirm") != "CLEAR":
        raise HTTPException(status_code=400,
                            detail='refusing: this drops the bond in that slot. Send {"confirm": "CLEAR"}.')
    svc = get_service()
    try:
        return await run_in_threadpool(svc.clear_ble_profile, body.get("side", "left"),
                                       body.get("index"), True)
    except (TransportError, DangerousCommandError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/restore-lighting")
async def restore_lighting(body: dict = Body(default={})) -> dict:
    """Both halves back to the stored colours and animation. One layer-list write; see
    DeviceService.restore_lighting."""
    svc = get_service()
    try:
        return await run_in_threadpool(svc.restore_lighting, body.get("side", "left"))
    except (TransportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/text-command")
async def text_command(body: dict = Body(...)) -> dict:
    svc = get_service()
    try:
        return await run_in_threadpool(
            svc.text_command, body.get("side", "left"), body["command"], bool(body.get("force", False))
        )
    except (TransportError, DangerousCommandError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/dump-settings")
async def dump_settings(body: dict = Body(default={})) -> dict:
    svc = get_service()
    try:
        return await run_in_threadpool(svc.dump_settings, body.get("side", "left"))
    except TransportError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/check-for-updates")
async def check_for_updates() -> dict:
    # OpenFlow has no external update dependency. Always report up to date.
    return {"updateAvailable": False, "reason": "OpenFlow has no external update source"}


# --- flash (write) : preview only for now (dry-run); real write is Phase C ---

@router.get("/api/module-variants")
async def module_variants() -> dict:
    """The stock profiles the "add profile" dropdown offers.

    Track appears twice because the module is ASYMMETRIC: flipping it to the other side reverses
    the physical button order and the scroll direction, so left and right ship different default
    maps. Either can occupy either bay -- the variant is about the bindings, not the position.
    """
    return {"variants": mprof.variants()}


@router.post("/rpc/create-module-profile")
async def create_module_profile(body: dict = Body(...)) -> dict:
    """Add a module profile, seeded from its stock map so it works immediately."""
    try:
        return await run_in_threadpool(mprof.create, body.get("variant"), body.get("name"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/rename-module-profile")
async def rename_module_profile(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(mprof.rename, body.get("configId"), body.get("name"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/delete-module-profile")
async def delete_module_profile(body: dict = Body(...)) -> dict:
    """Remove a profile. Refuses the last one of its type -- a module with no profile cannot be
    driven, and the device needs a config in the bay for it to work at all."""
    try:
        return await run_in_threadpool(mprof.delete, body.get("configId"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError as e:
        # A constraint we did not anticipate must still come back as a readable message.
        # Unhandled, it is a 500 that uvicorn answers by dropping the connection, and the
        # browser turns that into "failed to fetch" -- which says nothing about the cause.
        raise HTTPException(status_code=400, detail=f"cannot delete this profile: {e}")


@router.get("/api/app-shortcuts")
async def app_shortcuts(app: str = "", platform: str = "windows", q: str = "",
                        limit: int = 200, offset: int = 0) -> dict:
    """Per-application chords, on demand.

    Without `app`, returns just the application list -- 20 names and their counts. WITH one,
    returns that app's chords, filtered and paged. The file is 1.2 MB, so it deliberately does
    not ride along on /api/actions the way the 82-entry shortcut dictionary does.
    """
    from ..device import app_shortcuts as apps_mod
    if not app:
        return {"apps": await run_in_threadpool(apps_mod.apps),
                "platforms": list(apps_mod.PLATFORMS)}
    return await run_in_threadpool(apps_mod.search, app, platform, q, limit, offset)


@router.get("/api/device-state")
async def device_state() -> dict:
    """What we last saw on the keyboard, and when.

    Seeded into the app at startup so the live tags and blue dots survive a reload. `at` is the
    point of the endpoint as much as `modules` are: the caller must present it as "as of", not
    as the board's current state. `modules` is null after a flash.
    """
    return await run_in_threadpool(dstate.load)


@router.post("/rpc/export-module-profile")
async def export_module_profile(body: dict = Body(...)) -> dict:
    """One module profile as a portable JSON document (see db/module_io.py for the shape)."""
    from ..db import module_io
    try:
        return await run_in_threadpool(module_io.export_profile, body.get("configId"))
    except module_io.ProfileFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/import-module-profile")
async def import_module_profile(body: dict = Body(...)) -> dict:
    """Create a module profile from an exported document. Always a NEW profile."""
    from ..db import module_io
    try:
        return await run_in_threadpool(module_io.import_profile, body.get("profile"),
                                       body.get("name"))
    except module_io.ProfileFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"could not import this profile: {e}")


@router.get("/api/module-gestures")
async def module_gestures(types: str = "TUNE,TRACK,TOUCH,FLOAT") -> dict:
    """Per-module editable gestures + preset actions, for the gesture dropdowns.

    Static structure from the recovered field map; a live device read overlays the current
    binding later. Modules with no writable gesture fields (e.g. TRACK today) return an empty
    `gestures` list plus a `note`, so the UI can explain why."""
    out = []
    for mt in [t.strip().upper() for t in types.split(",") if t.strip()]:
        gestures = gesture_presets.gestures_for(mt)
        entry = {"module_type": mt, "gestures": gestures}
        if not gestures and module_fields.field_map(mt):
            entry["note"] = "no on-device gesture keypress fields (axis/speed only)"
        elif not module_fields.field_map(mt):
            entry["note"] = "no field map yet — connect this module and read it"
        out.append(entry)
    return {"modules": out}


@router.post("/rpc/read-modules")
async def read_modules(body: dict = Body(default={})) -> dict:
    """Read what is ACTUALLY on the keyboard for each module, and diff it against the app.

    The keymap read only ever asked for layers + LEDs, so module data never reached the UI.
    This returns, per module config we can match by uuid: its device slot, each gesture's
    device value, and whether it differs from what the app has stored. Read-only.
    """
    svc = get_service()
    try:
        read = await run_in_threadpool(svc.read_module_configs, body.get("side", "left"))
    except TransportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return await run_in_threadpool(_module_diff, read)


def _module_diff(read: dict, profile_id: str | None = None) -> dict:
    """Diff a module-config read against the app's stored bindings.

    Shared by /rpc/read-modules and /rpc/read-keyboard: the keymap read already pulls the
    module config list to resolve bays, so it can report which profiles are on the board
    without opening the port a second time.
    """
    out = _build_entries(read)

    # A read imports what it finds. Anything the board is running that no profile represents
    # becomes one, so the device's state is visible in the app and not just as a diff count.
    captured = mprof.capture_from_device(out)
    if captured:
        # Rebuild against the profiles that now exist, so each entry describes the row it
        # points at -- a capture must not inherit the diff rows of the profile it drifted from.
        out = _build_entries(read)
    # Bays follow what the board runs -- but only for the profile that REPRESENTS the board.
    # /rpc/read-modules imports nothing, so it names no profile and moves no bays.
    repointed = mprof.repoint_bays([(e.get("uuid"), e.get("matched")) for e in out], profile_id)
    # Persisted so a page reload does not throw away what we just learned. Stored WITH the time
    # it was taken -- the UI shows "as of HH:MM" rather than claiming it is current truth.
    saved = dstate.save(out, "read")
    return {"modules": out, "slotMap": read["by_uuid"], "captured": captured,
            "repointedBays": repointed, "at": saved["at"]}


def _build_entries(read: dict) -> list:
    """One entry per device slot, resolved against the app's current module profiles."""
    conn = db_connect()
    try:
        # SELECT * rather than a column list: `captured_from` is read below when present, and
        # older databases (and some test fixtures) predate the column.
        configs = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM module_configs")}
        # Keyed by behavior for the row the UI renders, and by (behavior, direction) for the
        # per-half rows a split writes. Collapsing on behavior alone made the two halves
        # overwrite each other, so whichever row the query happened to return last became "the"
        # app value -- and on a split axis that is one of the halves, not the combined row.
        # Every profile's settings rows, read here while the connection is open: the slot loop
        # below runs after the close (the tests' KeepOpen harness hid that on 2026-09-11).
        stored_settings: dict = {}
        for r in conn.execute("SELECT module_config_id, correlation_id, value FROM module_settings"):
            stored_settings.setdefault(r["module_config_id"], {})[r["correlation_id"]] = r["value"]
        bindings = {}
        for r in conn.execute("SELECT module_config_id, behavior, action_code, direction, invert "
                              "FROM module_bindings"):
            cfg = configs.get(r["module_config_id"])
            code = r["action_code"] or ""
            d = bindings.setdefault(r["module_config_id"], {})
            is_half = (cfg is not None
                       and r["behavior"] in module_fields.axis_halves(cfg["type"])
                       and code and " - " not in code and r["direction"] in ("-", "+"))
            if is_half:
                d[(r["behavior"], r["direction"])] = code
            else:
                d[r["behavior"]] = r["action_code"]
            # Invert is not a flag on the device -- it is a SELECTOR SWAP, so the only way to
            # see it on a read is to compare against the motion we know each half defaults to.
            if r["invert"]:
                d[(r["behavior"], "invert")] = True
    finally:
        conn.close()

    # The module LIST names each slot's TYPE in its entry's third byte (Touch 0, Track 1, Tune 2,
    # Float 3), so a slot is comparable by content whether or not the app has seen its uuid.
    list_types = _list_types(read.get("list"))

    out = []
    for uuid, slot in read["by_uuid"].items():
        cfg = configs.get(uuid)
        # THE MATCH IS ON CONTENT, NOT ON UUID. Every NayaFlow install writes its own uuids into
        # the list, so once any other NayaFlow has flashed the board not one slot uuid is known
        # here -- and until 2026-09-09 that made every slot "unknown": nothing was imported and
        # no profile showed as live, while the bindings on the board were byte for byte the
        # app's own stock profiles. The uuid decides nothing below. It only says which profile
        # to compare first, and supplies the type when the list cannot.
        mtype = cfg["type"] if cfg else list_types.get(slot)
        if mtype is None:
            out.append({"uuid": uuid, "slot": slot, "unknown": True,
                        "note": "on the device but not in the app's module configs, and the "
                                "module list carries no recognisable type for it"})
            continue
        fields = {int(f["field"]): (f["type"], bytes.fromhex(f["value"]))
                  for f in read["slots"].get(slot, read["slots"].get(str(slot), []))}

        # Every profile of the type, closest first. Among equals: the profile sharing the uuid,
        # then one captured from this very slot, then by name -- deterministic, and it keeps a
        # drifted original naming its own entry exactly as before.
        ranked = []
        for cid, c in configs.items():
            if c["type"] != mtype:
                continue
            # Compared under the candidate's OWN scroll direction convention: a Windows profile
            # names the board's vertical scroll records the way Windows scrolls (SCRUM-62).
            g, d = _compare(mtype, fields, bindings.get(cid, {}),
                            module_fields.convention_of(stored_settings.get(cid)))
            tie = 0 if cid == uuid else 1 if c.get("captured_from") == uuid else 2
            ranked.append((d, tie, c["name"], cid, g))
        ranked.sort(key=lambda t: t[:3])

        if cfg is not None:
            # The entry describes the slot as the uuid's own profile sees it, drift included.
            ref_id, ref_name = uuid, cfg["name"]
            gestures, differs = next((g, d) for d, _t, _n, cid, g in ranked if cid == uuid)
        elif ranked:
            # A uuid the app has never seen: the closest profile of its type stands in as the
            # reference. It names the entry and is what a capture starts from.
            differs, _t, ref_name, ref_id, gestures = ranked[0]
        else:
            # Nothing of this type in the app at all: compare against nothing, capture from nothing.
            ref_id, ref_name = None, f"{mtype.title()} module"
            gestures, differs = _compare(mtype, fields, {})
        # The slot's speeds and tick feedback against the reference profile's. Not part of the
        # match (gestures decide that); shown as drift, and imported whole by a capture.
        settings = _settings_rows(mtype, fields, stored_settings.get(ref_id, {}) if ref_id else {})
        entry = {"uuid": uuid, "slot": slot, "name": ref_name, "type": mtype,
                 "fieldCount": len(fields), "gestures": gestures, "differs": differs,
                 "trailing": max(0, len(fields) - _EXPECTED_FIELDS.get(mtype, len(fields))),
                 # What a capture of this slot starts from (module_profiles.capture_from_device).
                 "templateId": ref_id,
                 "settings": settings,
                 "settingsDiffer": sum(1 for x in settings if x["differs"])}
        if cfg is None:
            entry["foreign"] = True          # matched by content, or captured -- never by uuid

        # Which app profile is ACTUALLY on the board? Sharing the device's uuid is not enough:
        # an unflashed local edit keeps the uuid while no longer being what the keyboard runs,
        # and marking it "on the keyboard" is simply false. The profile on the board is the one
        # whose CONTENT matches, whichever row that is.
        entry["matched"] = ref_id if (ref_id and differs == 0) else None
        if entry["matched"] is None and ranked and ranked[0][0] == 0:
            _d, _t, name0, id0, g0 = ranked[0]
            # Report the slot as the matching profile sees it: identical, no drift.
            entry["matched"], entry["matchedName"], entry["matchedGestures"] = id0, name0, g0
        elif entry["matched"] is not None and cfg is None:
            # A foreign uuid matched by content. The UI resolves this slot through `matched`
            # and reads matchedGestures when the uuid differs, so give it those rows.
            entry["matchedName"], entry["matchedGestures"] = ref_name, gestures
        out.append(entry)
    return out


def _list_types(list_hex) -> dict:
    """{slot: module type} from the list's type byte. Lives in module_layout so the flash
    planner and this read path agree on what a slot is."""
    return module_layout.list_types(list_hex)


def _settings_rows(module_type: str, fields: dict, stored: dict) -> list:
    """The slot's setting fields against what the app holds for a profile: one row per setting
    the flash can write, {id, label, device, app, differs}.

    `stored` is the profile's module_settings rows ({id: value string}); a setting with no row
    compares against its schema default, which is what the flash would write for it. Settings
    do not take part in the content match -- gestures decide that -- but the drift is reported,
    and a capture imports the device's values (module_profiles.capture_from_device)."""
    device = module_fields.decode_settings(module_type, fields)
    schema = ud.SETTINGS_SCHEMA.get(module_type, ud._COMMON_POINTER)
    rows = []
    for f in schema:
        if f["id"] not in device:
            continue
        raw = stored.get(f["id"], f["default"])
        if f["kind"] == "toggle":
            app = raw if isinstance(raw, bool) else str(raw).strip().lower() == "true"
        else:
            try:
                app = int(float(raw))
            except (TypeError, ValueError):
                app = f["default"]
            # Compare in what the dial can actually hold: ticks_per_rotation is stored as
            # degrees per detent, so a profile at 100 lands on the board as 90 and is not drift.
            app = module_fields.setting_roundtrip(f["id"], app)
        dev = device[f["id"]]
        rows.append({"id": f["id"], "label": f["label"], "device": dev, "app": app,
                     "differs": dev != app})
    return rows


def _compare(module_type: str, fields: dict, app_bindings: dict, convention: str | None = None):
    """Device fields vs one app profile's bindings -> (per-gesture rows, count that differ).

    Covers BOTH kinds of gesture field:

    * single-field gestures (taps, swipes, the dial), one field each;
    * axis halves, TWO fields each, which `writable_fields` deliberately does not list.

    Leaving the halves out is what made a split axis unverifiable: the diff never looked at
    fields 0x0a-0x0d on a Tune, so `differs` could not see a motion change, a profile could be
    declared content-matched while its axes disagreed, and a capture taken from the read had no
    device truth for them and silently kept a copy of the source profile instead.

    `app_bindings` is {gesture: code} for the plain rows and {(gesture, sign): code} for the
    per-half overrides a split writes.
    """
    gestures, differs = [], 0
    # The Tune dial is TWO fields (0x22 clockwise, 0x23 counter-clockwise) but the app can
    # express it as one combined row, "C_VOL_DOWN - C_VOL_UP". Without this, a profile that
    # only carries the combined row compared each half against nothing and reported the
    # board's own volume bindings as drift, on every read, forever.
    pair_of = module_fields.pair_halves(module_type)
    for gesture, idx in sorted(module_fields.writable_fields(module_type).items()):
        typ, val = fields.get(idx, (None, b""))
        device = _decode_field(module_type, idx, typ, val, convention)
        app = app_bindings.get(gesture)
        if not app and gesture in pair_of:
            combined, sign = pair_of[gesture]
            minus, plus = module_fields.split_pair(app_bindings.get(combined))
            app = minus if sign == "-" else plus
        row = {"gesture": gesture, "field": idx}
        # EMPTY IS THE DEFAULT for a few gestures (module_fields.FIRMWARE_DEFAULTS): the Touch
        # left-clicks on a one-finger tap with 0x0b empty, because its firmware does that
        # itself. Reading empty as "unbound" here compared None against the app's M1, so the
        # stock Touch profile could never be live and every read minted a capture claiming the
        # tap was unset. An app row that is unbound is treated as the default as well: there is
        # nothing else this field can express.
        default = module_fields.firmware_default(module_type, gesture)
        if default is not None and device is None:
            device, row["firmwareDefault"] = default, True
        if module_fields.gesture_locked(module_type, gesture):
            # Locked: the field is always written empty and the editor offers no control, so
            # whatever an old row holds is not drift the user can act on.
            row["locked"] = True
            same = True
        else:
            same = _same_action(device, app) or (row.get("firmwareDefault", False) and not app)
        differs += 0 if same else 1
        gestures.append({**row, "device": device, "app": app, "differs": not same})

    for gesture, half in sorted(module_fields.axis_halves(module_type).items()):
        combined = app_bindings.get(gesture)      # the single row the UI renders for the axis
        # What each half is expected to drive, minus first. The combined row wins over the
        # gesture default; an EMPTY combined row means the axis is unbound and neither applies.
        pair = module_fields.split_pair(combined)
        base = list(module_fields.split_pair(half["default"]))
        for i in (0, 1):
            if pair[i]:
                base[i] = pair[i]
        # An inverted axis drives the OTHER motion from each half. Nothing on the board says so
        # -- there is no invert bit, which is why NayaFlow's own checkbox writes nothing -- so
        # the app's flag plus the default we know is the only way to tell "inverted, and
        # matching" from "drifted". Without it, ticking invert made the axis read as two
        # differences forever: the board held exactly what was asked for and still reported as
        # adrift, and no flash could resolve it.
        if app_bindings.get((gesture, "invert")):
            base = base[::-1]
        fw = module_fields.firmware_default(module_type, gesture)
        for sign, dflt in zip(("-", "+"), base):
            idx = half[sign]
            typ, val = fields.get(idx, (None, b""))
            device = _decode_field(module_type, idx, typ, val, convention)
            app = app_bindings.get((gesture, sign))
            if app is None:
                # A profile whose axis is UNBOUND says so with an empty row, and answering
                # "MOUSE_LEFT" for it made a capture of a board that really has nothing there
                # differ from the board forever -- so it could never be marked live, and every
                # read minted another copy of it.
                app = dflt if (combined is None or " - " in str(combined)) else (combined or None)
            row = {"gesture": gesture, "half": sign, "field": idx}
            if fw is not None and device is None:
                # The Touch's one-finger cursor: the firmware drives this half itself while the
                # field is empty, always with the stock motion for the sign (nothing on the
                # device inverts it). See module_fields.FIRMWARE_DEFAULTS.
                device = module_fields.split_pair(fw)[0 if sign == "-" else 1]
                row["firmwareDefault"] = True
            if module_fields.gesture_locked(module_type, gesture):
                row["locked"] = True
                same = True
            else:
                same = _same_action(device, app)
            differs += 0 if same else 1
            gestures.append({**row, "device": device, "app": app, "differs": not same})
    return gestures, differs


# A Track config is 15 fields; anything past that is orphaned data from a previous module
# (NayaFlow writes a shorter config over a longer one without truncating).
_EXPECTED_FIELDS = {"TRACK": 15}


def _same_action(device, app) -> bool:
    """Compare a decoded device action with the app's action_code, modifier-order-insensitive.

    We decode a chord in HID modifier-bit order (LCTRL, LSHIFT, LALT, LGUI) while NayaFlow
    stored whatever order the user built it in, so "LCTRL + LGUI + LEFT" and "LGUI + LCTRL +
    LEFT" are the same binding. Comparing the raw strings reports every shortcut as changed,
    which would bury the differences that are real.
    """
    if device is None or app is None or device == "" or app == "":
        return not device and not app
    if device == app:
        return True
    # An action with no HID record -- LED brightness is the one in the stock profiles -- is
    # stored by the board as an empty keypress. Comparing the decoded strings called that a
    # difference on every single read, which no flash could ever resolve: the app said
    # LED_BRIGHTNESS_UP, the board said an empty keypress, and there is no third state to
    # move to. It permanently blocked the profile from reading as live and minted a fresh
    # capture each time. The board is carrying what this action looks like on the board.
    if device == remap.EMPTY_KEYPRESS and not remap.encodable(app):
        return True
    parts = lambda v: sorted(t.strip().upper() for t in str(v).split("+"))
    return parts(device) == parts(app)


def _decode_field(module_type: str, idx: int, typ, val: bytes, convention: str | None = None):
    """One device field -> the app's action_code vocabulary, or None if unbound.

    Dispatches on the record TYPE, not on the field's nominal kind. A gesture field is not
    type-locked -- a split axis half bound to a key is a KEY_PRESS sitting in a field the map
    calls "axis", and a Track button bound to a letter is the same story. Reading the kind
    first decoded both as RAW.
    """
    if typ is None or typ == remap.NONE_BEH or not val:
        return None
    try:
        if typ == remap.KEY_PRESS:
            return keymap_read.decode_keypress(val)[1]
        if typ == remap.TWO_WORD:
            category, selector = remap.decode_two_word(val)
            if category == remap.MOUSE_CATEGORY:
                return remap.MOUSE_MASK_REV.get(selector) or f"RAW_{val.hex()}"
            return (module_fields.motion_name(module_type, idx, category, selector, convention)
                    or f"RAW_{val.hex()}")
    except Exception:
        return f"RAW_{val.hex()}"
    return f"RAW_{val.hex()}"


def _device_slots(mod_read) -> set | None:
    """Which module slots the board actually holds.

    Passed to the planner separately because `current` is built from a KEYMAP read, whose
    `.modules` is empty -- so orphan collection looking at `current.modules` found nothing,
    every time. None means we did not read the modules and must not guess.
    """
    if not mod_read:
        return None
    return {int(s) for s in (mod_read.get("slots") or {})}


def _flash_preview(profile_id: str | None = None, side: str = "left") -> dict:
    # The module layout needs to know what the board already carries -- which profiles have
    # slots and what a new slot can be templated from. Without that read the preview can still
    # show the keymap, but it must not invent a module plan.
    mod_read = None
    try:
        mod_read = get_service().read_module_configs(side)
    except Exception:
        pass
    conn = db_connect()
    try:
        desired = flash_mod.desired_from_db(conn, profile_id)
        layout = (flash_mod.apply_module_layout(desired, conn, mod_read)
                  if mod_read is not None else None)
    finally:
        conn.close()
    out = flash_mod.flash(desired, dry_run=True, full=True)
    out["profileId"] = desired.profile_id
    out["modules"] = _layout_summary(layout)
    # Bays the first layer leaves unarmed. The UI blocks Confirm on these (SCRUM-61).
    out["baseBayGaps"] = list((layout or {}).get("baseBayGaps") or [])
    # What removing the unreferenced slots WOULD do, reported but never done here. The preview
    # is how the user finds out these exist at all: an orphan is invisible otherwise, and slot 5
    # on the reference board has sat there unreferenced for weeks reading back as "unknown".
    slots = _device_slots(mod_read)
    if slots is not None and desired.module_list is not None:
        gone = sorted(slots - set(desired.module_list))
        out["orphans"] = [{"slot": n, "name": _slot_name(n, mod_read)} for n in gone]
    return out


def _slot_name(slot: int, mod_read) -> str | None:
    """The profile a slot holds, if the app knows it. An orphan NayaFlow created has no name
    here, and saying so is better than inventing one."""
    uuid = next((u for u, s in (mod_read.get("by_uuid") or {}).items() if int(s) == slot), None)
    if uuid is None:
        return None
    conn = db_connect()
    try:
        row = conn.execute("SELECT name FROM module_configs WHERE id=?", (uuid,)).fetchone()
        return row["name"] if row else None
    finally:
        conn.close()


def _layout_summary(layout) -> dict | None:
    """What the module plan will do, in the terms the UI shows: which profiles get slots and
    which of those are being added."""
    if layout is None:
        return {"available": False,
                "note": "the keyboard could not be read, so no module profiles are planned"}
    conn = db_connect()
    try:
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM module_configs")}
    finally:
        conn.close()
    reclaimed = layout.get("reclaimed") or {}
    return {"available": True,
            "slots": [{"slot": slot, "id": cid, "name": names.get(cid, cid),
                       "new": cid in layout["allocated"],
                       # The profile this slot held until now, when it is being reused.
                       "replaces": names.get(reclaimed[slot], reclaimed[slot]) if slot in reclaimed else None}
                      for cid, slot in sorted(layout["slot_for"].items(), key=lambda x: x[1])],
            "added": len(layout["allocated"]),
            "reclaimed": [{"slot": s, "was": names.get(u, u)} for s, u in sorted(reclaimed.items())]}


@router.post("/rpc/flash")
async def flash_write(body: dict = Body(default={})) -> dict:
    """WRITE a profile to the keyboard. The only endpoint that changes the device.

    Requires `{"confirm": "FLASH"}` and an explicit `profileId`. Two modes, with genuinely
    different safety properties:

    **mode="sync" (default).** Takes a fresh device read first and plans against it. This is
    what makes preservation possible: compute_plan uses the read to carry through everything
    the app does not model -- the module->dock bindings at layer positions 0x4A-0x51, TRANS
    records, and both banks of keys the profile does not set -- and to know which module
    fields are stale. (A key the profile DOES set owns its second bank: with no double-tap /
    tap+hold in the profile, that slot is written NONE rather than carried through, because a
    stale shadow there is exactly what made NayaFlow fail to verify; see flash._own_second_bank.)
    If the read fails, the flash is refused, because a plan built without it would blank all
    of that.

    **mode="recovery".** For a board that can no longer be read. It skips the read, so NOTHING
    can be preserved: every position in both banks is written explicitly and anything the app
    does not model is lost, module->dock assignments included. Requires
    `{"acknowledgeRecovery": true}` on top of the confirm, and is always a full write.

    Every frame's ack is checked, the first bad one aborts, and a sync flash is verified by
    reading the device back.
    """
    if body.get("confirm") != "FLASH":
        raise HTTPException(status_code=400,
                            detail='refusing: this writes to the keyboard. Send {"confirm": "FLASH"}.')
    mode = body.get("mode", "sync")
    if mode not in ("sync", "recovery"):
        raise HTTPException(status_code=400, detail=f'unknown mode {mode!r} (sync|recovery)')
    if mode == "recovery" and body.get("acknowledgeRecovery") is not True:
        raise HTTPException(status_code=400, detail=(
            "recovery mode cannot preserve anything the app does not model -- module-to-dock "
            "assignments, transparent keys and second-bank bindings are all overwritten. "
            'Send {"acknowledgeRecovery": true} to accept that.'))
    svc = get_service()
    side = body.get("side", "left")
    full = True if mode == "recovery" else bool(body.get("full", False))

    def _run_unlocked() -> dict:
        before, current, mod_read = None, None, None
        if mode == "sync":
            before = svc.read_keymap(side)                   # mandatory: the preservation baseline
            current = flash_mod.desired_from_device_read(before)
            # Mandatory too when the profile assigns module bays: allocating a slot or
            # templating a new config is impossible without knowing what the board carries.
            mod_read = svc.read_module_configs(side)
        conn = db_connect()
        try:
            # Scoped to ONE profile: the layers table spans all of them, so an unscoped plan
            # writes whichever profile the query returned last.
            desired = flash_mod.desired_from_db(conn, body.get("profileId"))
            # Recovery mode skips the read, so there is nothing to allocate slots against and
            # no config to template a new one from. It leaves the module layout alone rather
            # than guessing -- consistent with everything else recovery does not preserve.
            layout = (flash_mod.apply_module_layout(desired, conn, mod_read)
                      if mod_read is not None else None)
        finally:
            conn.close()
        # The first layer must arm every module bay (a profile or "disabled"); a gap leaves that
        # module unconfigured on the board. Refused unless the caller says it knows (SCRUM-61).
        gaps = list((layout or {}).get("baseBayGaps") or [])
        if gaps and body.get("allowBaseBayGaps") is not True:
            raise HTTPException(status_code=400, detail=(
                "the first layer leaves module bays unset: " + ", ".join(gaps)
                + ". Pick a profile (or 'disabled') for each on the Bindings board, or pass "
                  "allowBaseBayGaps=true to flash anyway."))

        dev = svc._require_side(side)
        dest = svc._dest_for_side(dev.side)
        transport = svc._transport_for(dev.port, dest)
        result = flash_mod.flash(
            desired, transport=transport, dest=dest, current=current, full=full,
            dry_run=False,
            # Removing a module slot the board carries and this profile does not reference.
            # Opt-in per flash: it drops a list entry and blanks a slot, which is the one
            # destructive thing a flash can do, so the caller asks rather than us deciding.
            collect_orphans=bool(body.get("collectOrphans")),
            device_slots=_device_slots(mod_read),
            # A recovery flash targets a board we could not read, so do not claim a verify we
            # cannot trust; report it as sent-unverified and let the caller re-read if it can.
            reader=(None if mode == "recovery"
                    else lambda: flash_mod.desired_from_device_read(svc.read_keymap(side))),
        )
        result["mode"] = mode
        result["profileId"] = desired.profile_id
        # Read the MODULES back and publish them, so the live tags and blue dots are right the
        # moment a flash finishes.
        #
        # The flash already verifies -- but its verify reader is read_keymap, which covers
        # layers and LEDs and never touches the module configs. So clearing on its own threw
        # away what we knew and replaced it with nothing, and the user had to read again to see
        # the result of a write that had just been checked. This is the read they were going to
        # do anyway, on a port that is already open.
        #
        # A recovery flash is exempt: it targets a board we could not read in the first place.
        dstate.clear("flash")
        if mode != "recovery" and result.get("status") == "verified":
            try:
                after = _module_diff(svc.read_module_configs(side), desired.profile_id)
                result["moduleState"] = after
                result["deviceStateAt"] = dstate.save(after["modules"], "flash-verify")["at"]
            except Exception as e:
                # Never fail a good flash because the follow-up read did not work. The state
                # stays cleared, which is the honest fallback: we know we wrote, not what is
                # there now.
                result["moduleStateError"] = f"{type(e).__name__}: {e}"
        result["modules"] = _layout_summary(layout)
        result["backup"] = None if before is None else {
            "layers": {str(i): [[p, t, bytes(v).hex()] for p, t, v in recs]
                       for i, recs in before["layers"].items()},
            "led": {str(i): [[a, b, c] for a, b, c in entries]
                    for i, entries in before.get("led", {}).items()},
        }
        return result

    def _run() -> dict:
        # The WHOLE flash -- the preservation read, every write frame and the verify read-back
        # -- holds the service lock, so the live-status tick (service.tick, every ~6 s per half,
        # under this same lock) waits behind it instead of interleaving its four commands with
        # the flash's frames on the same port. Without this, a chunked LED or layer write lost
        # its continuation frame's ack to a tick and the flash aborted with "bad or missing
        # ack" ("led 0", frame 1, ack None on 2026-09-16); the reads inside already took the
        # lock, the write between them never did. RLock, so the nested reads still work.
        with svc._lock:
            return _run_unlocked()

    try:
        return await run_in_threadpool(_run)
    except flash_mod.AmbiguousProfileError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TransportError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.post("/rpc/flash-preview")
async def flash_preview(body: dict = Body(default={})) -> dict:
    """Dry-run the full flash from the current DB: returns the write plan + a diff summary +
    the rendered frames. Sends NOTHING to the device. The Flash button shows this before a real
    write, which requires a separate explicit confirm). Takes the same profileId as /rpc/flash
    so the preview shows the plan that Confirm would actually send."""
    try:
        result = await run_in_threadpool(_flash_preview, body.get("profileId"),
                                         body.get("side", "left"))
    except Exception as e:  # DB/encode errors surface cleanly to the UI
        # The UI gets a short message; the log gets the stack. Without this a report of
        # "flash preview failed: <something>" cannot be located at all -- the whole
        # traceback was discarded here, and the log a user sent back held nothing but
        # uvicorn's startup lines (SCRUM-95).
        log.exception("flash preview failed")
        raise HTTPException(status_code=400, detail=f"flash preview failed: {e}")
    return {"dryRun": True, **result}


@router.post("/rpc/set-layer-bay")
async def set_layer_bay(body: dict = Body(...)) -> dict:
    """Pick the module profile a layer runs in one bay (the board's module dropdowns)."""
    try:
        return await run_in_threadpool(
            ud.set_layer_bay, body["layerId"], body["moduleType"],
            body.get("configId"), body.get("side"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-axis-split")
async def set_axis_split(body: dict = Body(...)) -> dict:
    """Bind one direction of an axis gesture to a key, or clear it back to motion."""
    try:
        return await run_in_threadpool(ud.set_axis_split, body["configId"], body["behavior"],
                                       body["half"], body.get("actionCode"))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/set-axis-invert")
async def set_axis_invert(body: dict = Body(...)) -> dict:
    """Flip an axis gesture's direction (written as opposite selector signs)."""
    try:
        return await run_in_threadpool(ud.set_axis_invert, body["configId"], body["behavior"],
                                       bool(body.get("invert")))
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
