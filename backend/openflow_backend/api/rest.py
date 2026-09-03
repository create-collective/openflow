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
from ..db import module_profiles as mprof
from ..db import profiles as prof
from ..db import settings as settings_db
from ..db import userdata as ud
from ..db.database import connect as db_connect
from ..device import actions_catalog, flash as flash_mod, gesture_presets, keymap_read, module_fields, remap
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

    conn = db_connect()
    try:
        configs = {r["id"]: dict(r) for r in
                   conn.execute("SELECT id, name, type FROM module_configs")}
        bindings = {}
        for r in conn.execute("SELECT module_config_id, behavior, action_code FROM module_bindings"):
            bindings.setdefault(r["module_config_id"], {})[r["behavior"]] = r["action_code"]
    finally:
        conn.close()

    out = []
    for uuid, slot in read["by_uuid"].items():
        cfg = configs.get(uuid)
        if cfg is None:
            out.append({"uuid": uuid, "slot": slot, "unknown": True,
                        "note": "on the device but not in the app's module configs"})
            continue
        fields = {int(f["field"]): (f["type"], bytes.fromhex(f["value"]))
                  for f in read["slots"].get(slot, read["slots"].get(str(slot), []))}
        gestures, differs = [], 0
        for gesture, idx in sorted(module_fields.writable_fields(cfg["type"]).items()):
            typ, val = fields.get(idx, (None, b""))
            device = _decode_field(cfg["type"], idx, typ, val)
            app = bindings.get(uuid, {}).get(gesture)
            same = _same_action(device, app)
            differs += 0 if same else 1
            gestures.append({"gesture": gesture, "field": idx, "device": device,
                             "app": app, "differs": not same})
        out.append({"uuid": uuid, "slot": slot, "name": cfg["name"], "type": cfg["type"],
                    "fieldCount": len(fields), "gestures": gestures, "differs": differs,
                    "trailing": max(0, len(fields) - _EXPECTED_FIELDS.get(cfg["type"], len(fields)))})
    return {"modules": out, "slotMap": read["by_uuid"]}


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
    parts = lambda v: sorted(t.strip().upper() for t in str(v).split("+"))
    return parts(device) == parts(app)


def _decode_field(module_type: str, idx: int, typ, val: bytes):
    """One device field -> the app's action_code vocabulary, or None if unbound."""
    if typ is None or typ == remap.NONE_BEH or not val:
        return None
    kind = module_fields.field_map(module_type).get(f"0x{idx:02x}", {}).get("kind")
    try:
        if kind == "mouse_button":
            return remap.decode_mouse_button(val)
        if kind == "keypress":
            return keymap_read.decode_keypress(val)[1]
    except Exception:
        return f"RAW_{val.hex()}"
    return f"RAW_{val.hex()}"


def _flash_preview(profile_id: str | None = None) -> dict:
    conn = db_connect()
    try:
        desired = flash_mod.desired_from_db(conn, profile_id)
    finally:
        conn.close()
    out = flash_mod.flash(desired, dry_run=True, full=True)
    out["profileId"] = desired.profile_id
    return out


@router.post("/rpc/flash")
async def flash_write(body: dict = Body(default={})) -> dict:
    """WRITE a profile to the keyboard. The only endpoint that changes the device.

    Requires `{"confirm": "FLASH"}` and an explicit `profileId`. Two modes, with genuinely
    different safety properties:

    **mode="sync" (default).** Takes a fresh device read first and plans against it. This is
    what makes preservation possible: compute_plan uses the read to carry through everything
    the app does not model -- the module->dock bindings at layer positions 0x4A-0x51, TRANS
    records, and second-bank positions -- and to know which module fields are stale. If the
    read fails, the flash is refused, because a plan built without it would blank all of that.

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

    def _run() -> dict:
        before, current = None, None
        if mode == "sync":
            before = svc.read_keymap(side)                   # mandatory: the preservation baseline
            current = flash_mod.desired_from_device_read(before)
        conn = db_connect()
        try:
            # Scoped to ONE profile: the layers table spans all of them, so an unscoped plan
            # writes whichever profile the query returned last.
            desired = flash_mod.desired_from_db(conn, body.get("profileId"))
        finally:
            conn.close()

        dev = svc._require_side(side)
        dest = svc._dest_for_side(dev.side)
        transport = svc._transport_for(dev.port, dest)
        result = flash_mod.flash(
            desired, transport=transport, dest=dest, current=current, full=full,
            dry_run=False,
            # A recovery flash targets a board we could not read, so do not claim a verify we
            # cannot trust; report it as sent-unverified and let the caller re-read if it can.
            reader=(None if mode == "recovery"
                    else lambda: flash_mod.desired_from_device_read(svc.read_keymap(side))),
        )
        result["mode"] = mode
        result["profileId"] = desired.profile_id
        result["backup"] = None if before is None else {
            "layers": {str(i): [[p, t, bytes(v).hex()] for p, t, v in recs]
                       for i, recs in before["layers"].items()},
            "led": {str(i): [[a, b, c] for a, b, c in entries]
                    for i, entries in before.get("led", {}).items()},
        }
        return result

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
        result = await run_in_threadpool(_flash_preview, body.get("profileId"))
    except Exception as e:  # DB/encode errors surface cleanly to the UI
        raise HTTPException(status_code=400, detail=f"flash preview failed: {e}")
    return {"dryRun": True, **result}
