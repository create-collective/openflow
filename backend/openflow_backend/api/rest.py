"""REST routes reimplementing NayaFlow's flow-bg-server contract.

Route names and shapes are taken from the recovered renderer
(extracted/NayaFlow-1.25.1/.../index-mihUmo_8.js). See docs/api-contract.md.
Not every original route is implemented in Phase 1 — the device-facing and
user-data routes are, and firmware/pairing routes return an explicit
not-implemented status rather than 404 so the UI can surface state cleanly.
"""

from __future__ import annotations

import platform

from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool

from .. import __version__
from ..db import macros as mac
from ..db import userdata as ud
from ..device import actions_catalog
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


@router.get("/api/userdata")
async def userdata() -> dict:
    """Profiles -> layers -> keys -> bindings, from the offline SQLite store."""
    return await run_in_threadpool(ud.get_userdata)


@router.get("/api/modules")
async def modules() -> dict:
    """Module configs (Touch/Track/Tune) with gesture bindings + settings."""
    return await run_in_threadpool(ud.get_modules)


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
