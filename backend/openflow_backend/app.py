"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import rest, sse
from .api.state import shutdown_service
from .db import backup as bak
from .db.database import init_db

AUTO_BACKUP_INTERVAL_S = 30 * 60  # every 30 minutes, like NayaFlow


async def _auto_backup_loop():
    while True:
        await asyncio.sleep(AUTO_BACKUP_INTERVAL_S)
        try:
            await asyncio.to_thread(bak.create_backup, "auto")
        except Exception:
            pass  # never let a backup failure take down the app


# NayaCore's interval. Each tick is a few short round trips per half under the service lock;
# a flash in progress simply delays it.
DEVICE_POLL_INTERVAL_S = 6.0


async def _device_poll_loop():
    from .api.state import get_service
    while True:
        try:
            await asyncio.to_thread(get_service().tick_all)
        except Exception:
            pass  # a bad tick is a missed reading, never a crashed app
        await asyncio.sleep(DEVICE_POLL_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    tasks = [asyncio.create_task(_auto_backup_loop()), asyncio.create_task(_device_poll_loop())]
    yield
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    shutdown_service()


def create_app() -> FastAPI:
    app = FastAPI(title="OpenFlow backend", lifespan=lifespan)

    # Local-only app; the renderer runs from a Vite dev server in development and
    # from Electron in production. Allow localhost origins so the dev server works.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(rest.router)
    app.include_router(sse.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
