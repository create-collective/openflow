"""Server-Sent Events endpoint.

NayaFlow's renderer opens one EventSource at `/sse` and listens for named events:
    sse:naya-devices-stream, sse:flash-keymap-state,
    sse:device-operation-options, sse:ui-state-change, sse:main-process-quit
We keep those names so the rebuilt renderer's SSE hooks match. Phase 1 drives the
device-list stream from a cheap USB-enumeration poll (no serial handshake); the
flash-keymap / operation-options streams are placeholders until Phase 2/3.

`sse:flash-progress` is ours, added for SCRUM-102: a firmware run's steps as they happen.

TWO THINGS HERE ARE LOAD-BEARING, AND BOTH ARE ABOUT NOT BLOCKING
-----------------------------------------------------------------
`svc.snapshot()` takes the service lock, and it used to be called straight from the event loop.
A firmware flash holds that lock for its whole four-to-ten minutes (flash_procedure.run, and it
must: nothing may touch either COM port mid-write). An RLock.acquire on the event loop thread
stops the ENTIRE backend -- every route, not just this stream -- for as long as the holder keeps
it. So the app would go dead exactly while running the one operation that most needs to explain
itself. The snapshot now happens in the threadpool, with the enumeration, in one hop.

And while a run is going the device poll is skipped entirely. It would only queue behind the run's
lock, and it has nothing to say anyway: a half in MCUboot enumerates as a product id the poll
cannot recognise. The tick becomes the progress tick instead, and when the run ends the device
signature is cleared so the next tick re-sends a full device state -- which is what the versions
on screen changed to.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse

from ..device import flash_runs as runs
from .state import get_service

router = APIRouter()

POLL_INTERVAL_S = 2.0
# During a run the only thing that moves is the run, and it moves in steps a user is watching --
# the upload reports every 5 %, and a step boundary is the moment the wording on screen changes.
FLASH_INTERVAL_S = 0.5


def compose(devices: list, snapshot: dict) -> tuple[str, dict]:
    """The devices event: enumeration plus the poll loop's last snapshot. The signature the
    stream compares leaves timestamps out, so a tick that changed nothing sends nothing."""
    payload = {"devices": devices, "status": snapshot}
    quiet = {"devices": devices,
             "released": bool(snapshot.get("released")),
             "status": {"halves": [{k: v for k, v in h.items() if k != "at"}
                                   for h in snapshot.get("halves", [])]}}
    return json.dumps(quiet, sort_keys=True), payload


def _poll(svc) -> tuple[str, dict]:
    """Enumeration and the last tick's snapshot, both off the event loop. See the module note."""
    return compose(svc.list_devices(), svc.snapshot())


async def event_stream(svc, disconnected):
    """The stream itself, as a plain generator so it can be driven by a test without a socket.

    `disconnected` is awaited once per tick and ends the stream when it answers True.
    """
    yield {"event": "sse:ui-state-change", "data": json.dumps({"ready": True})}
    last_signature: str | None = None
    seen_seq = 0
    watching: str | None = None
    while True:
        if await disconnected():
            break

        run = runs.current() if runs.active() else None
        if run is not None:
            # A client that connected mid-run has seen nothing of it, so the first tick of a run
            # it is not already watching replays the whole thing from seq 0.
            if watching != run.id:
                watching, seen_seq = run.id, 0
            state = run.snapshot(since=seen_seq)
            seen_seq = state["seq"]
            yield {"event": "sse:flash-progress", "data": json.dumps(state)}
            await asyncio.sleep(FLASH_INTERVAL_S)
            continue

        if watching is not None:
            # The run finished between ticks. Send its ending -- verdict included, and the tail
            # of events the last tick did not have -- then fall back to device polling with the
            # signature cleared, so the new firmware version reaches the screen on the very next
            # tick instead of looking unchanged.
            ended = runs.get(watching)
            if ended is not None:
                yield {"event": "sse:flash-progress",
                       "data": json.dumps(ended.snapshot(since=seen_seq))}
            watching, seen_seq, last_signature = None, 0, None

        signature, payload = await run_in_threadpool(_poll, svc)
        if signature != last_signature:
            last_signature = signature
            yield {
                "event": "sse:naya-devices-stream",
                "data": json.dumps(payload),
            }
        await asyncio.sleep(POLL_INTERVAL_S)


@router.get("/sse")
async def sse(request: Request) -> EventSourceResponse:
    return EventSourceResponse(event_stream(get_service(), request.is_disconnected))
