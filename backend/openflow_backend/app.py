"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from .api import rest, sse
from .api.state import shutdown_service
from .config import renderer_dir
from .db import backup as bak
from .db.database import init_db
from .seed import ensure_seeded

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


class _Renderer(StaticFiles):
    """The built renderer, served at / so page and API share one origin (no CORS, no file://).

    index.html is never cached: after an upgrade the same origin and port would otherwise hand
    the browser a stale page pointing at hashed assets that no longer exist, and the window
    would be blank. The hashed assets themselves may be cached as usual."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["cache-control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_seeded()          # first run: the bundled snapshot, so the app never opens empty
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

    # Local-only app. In development the renderer runs from the Vite dev server on another
    # port, so localhost origins are allowed; in the desktop app the renderer is served by this
    # process (the mount below) and no cross-origin request happens at all.
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

    # The built renderer, when there is one (frontend/dist in a checkout, resources/renderer in
    # the frozen bundle). Mounted LAST so every /api, /rpc, /sse and /health route wins; the
    # HashRouter keeps all navigation on /, so no history fallback is needed.
    rd = renderer_dir()
    if rd is not None and (rd / "index.html").is_file():
        app.mount("/", _Renderer(directory=str(rd), html=True), name="renderer")

    return app


app = create_app()
