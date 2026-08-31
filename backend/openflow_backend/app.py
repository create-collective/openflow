"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import rest, sse
from .api.state import shutdown_service
from .db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
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
