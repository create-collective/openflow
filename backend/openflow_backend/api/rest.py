"""REST routes reimplementing NayaFlow's flow-bg-server contract.

Route names and shapes are taken from the recovered renderer
(extracted/NayaFlow-1.25.1/.../index-mihUmo_8.js). See docs/api-contract.md.
Not every original route is implemented in Phase 1 — the device-facing and
user-data routes are, and firmware/pairing routes return an explicit
not-implemented status rather than 404 so the UI can surface state cleanly.
"""

from __future__ import annotations

import platform

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import __version__
from ..db import backup as bak
from ..db import keymap_import as kmi
from ..db import macros as mac
from ..db import profiles as prof
from ..db import settings as settings_db
from ..db import userdata as ud
from ..db.database import connect as db_connect
from ..device import actions_catalog, flash as flash_mod, gesture_presets, module_fields
from ..device.commands import CommandError, dispatch
from ..device.service import DangerousCommandError, TransportError
from .state import get_service

router = APIRouter()


# --- /api (GET) ------------------------------------------------------------

@router.get("/api/info/system")
async def info_system() -> dict:
    return {
        "app": "OpenFlow",
        "backendVersion": __version__,
        "os": platform.system(),
        "osVersion": platform.version(),
        "arch": platform.machine(),
    }


@router.get("/api/ui/state")
async def ui_state() -> dict:
    svc = get_service()
    devices = await run_in_threadpool(svc.list_devices)
    return {"ready": True, "deviceCount": len(devices)}


@router.get("/api/devices")
async def devices() -> dict:
    svc = get_service()
    return {"devices": await run_in_threadpool(svc.list_devices)}


@router.get("/api/status")
async def status(verbose: bool = False) -> dict:
    svc = get_service()
    return {"halves": await run_in_threadpool(svc.status_all, verbose)}


@router.post("/rpc/read-keyboard")
async def read_keyboard(body: dict = Body(default={})) -> dict:
    """Read the map currently on the keyboard and import it as a new profile."""
    svc = get_service()
    side = body.get("side", "left")
    try:
        read = await run_in_threadpool(svc.read_keymap, side)
    except TransportError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return await run_in_threadpool(kmi.import_read, read, body.get("name"))


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


@router.post("/rpc/set-setting")
async def set_setting(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(settings_db.set_setting, body["key"], body["value"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


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
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rpc/delete-macro-step")
async def delete_macro_step(body: dict = Body(...)) -> dict:
    return await run_in_threadpool(mac.delete_step, body["stepId"])


@router.post("/rpc/reorder-macro-steps")
async def reorder_macro_steps(body: dict = Body(...)) -> dict:
    return await run_in_threadpool(mac.reorder_steps, body["macroId"], body["orderedIds"])


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


@router.post("/rpc/set-base-layer")
async def set_base_layer(body: dict = Body(...)) -> dict:
    try:
        return await run_in_threadpool(ud.set_base_layer, body["layerId"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


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


def _flash_preview() -> dict:
    conn = db_connect()
    try:
        desired = flash_mod.desired_from_db(conn)
    finally:
        conn.close()
    return flash_mod.flash(desired, dry_run=True, full=True)


@router.post("/rpc/flash-preview")
async def flash_preview(body: dict = Body(default={})) -> dict:
    """Dry-run the full flash from the current DB: returns the write plan + a diff summary +
    the rendered frames. Sends NOTHING to the device. The Flash button shows this before a real
    write (which requires a separate explicit confirm and is Phase C)."""
    try:
        result = await run_in_threadpool(_flash_preview)
    except Exception as e:  # DB/encode errors surface cleanly to the UI
        raise HTTPException(status_code=400, detail=f"flash preview failed: {e}")
    return {"dryRun": True, **result}
