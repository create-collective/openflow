"""Server-Sent Events endpoint.

NayaFlow's renderer opens one EventSource at `/sse` and listens for named events:
    sse:naya-devices-stream, sse:flash-keymap-state,
    sse:device-operation-options, sse:ui-state-change, sse:main-process-quit
We keep those names so the rebuilt renderer's SSE hooks match. Phase 1 drives the
device-list stream from a cheap USB-enumeration poll (no serial handshake); the
flash-keymap / operation-options streams are placeholders until Phase 2/3.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse

from .state import get_service

router = APIRouter()

POLL_INTERVAL_S = 2.0


def compose(devices: list, snapshot: dict) -> tuple[str, dict]:
    """The devices event: enumeration plus the poll loop's last snapshot. The signature the
    stream compares leaves timestamps out, so a tick that changed nothing sends nothing."""
    payload = {"devices": devices, "status": snapshot}
    quiet = {"devices": devices,
             "released": bool(snapshot.get("released")),
             "status": {"halves": [{k: v for k, v in h.items() if k != "at"}
                                   for h in snapshot.get("halves", [])]}}
    return json.dumps(quiet, sort_keys=True), payload


@router.get("/sse")
async def sse(request: Request) -> EventSourceResponse:
    svc = get_service()

    async def event_stream():
        yield {"event": "sse:ui-state-change", "data": json.dumps({"ready": True})}
        last_signature: str | None = None
        while True:
            if await request.is_disconnected():
                break
            devices = await run_in_threadpool(svc.list_devices)
            signature, payload = compose(devices, svc.snapshot())
            if signature != last_signature:
                last_signature = signature
                yield {
                    "event": "sse:naya-devices-stream",
                    "data": json.dumps(payload),
                }
            await asyncio.sleep(POLL_INTERVAL_S)

    return EventSourceResponse(event_stream())
