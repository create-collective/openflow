"""/rpc/shutdown stops the server cleanly, and only for whoever launched it.

The desktop shell hands the backend a per-launch token (OPENFLOW_INSTANCE); /api/info/system
echoes it so the shell can tell its own sidecar from any other server on the port, and
/rpc/shutdown accepts only that token. A clean stop runs the lifespan shutdown (the device port
is closed, the poll loop cancelled), which a killed process never does. No hardware.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from fastapi import FastAPI                        # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

from openflow_backend.api import rest              # noqa: E402


def _client():
    app = FastAPI()
    app.include_router(rest.router)
    app.state.server = types.SimpleNamespace(should_exit=False)
    return app, TestClient(app)


def test_info_echoes_the_instance_token_and_shutdown_needs_it(monkeypatch):
    monkeypatch.setenv("OPENFLOW_INSTANCE", "launch-42")
    app, client = _client()
    info = client.get("/api/info/system").json()
    assert info["instance"] == "launch-42" and info["frozen"] is False
    assert client.post("/rpc/shutdown", json={}).status_code == 403
    assert client.post("/rpc/shutdown", json={"instance": "someone-else"}).status_code == 403
    assert app.state.server.should_exit is False
    r = client.post("/rpc/shutdown", json={"instance": "launch-42"})
    assert r.status_code == 200 and r.json() == {"status": "stopping"}
    assert app.state.server.should_exit is True
    print("  the token is echoed; the wrong token is refused; the right one sets should_exit")


def test_without_a_token_nothing_can_shut_us_down(monkeypatch):
    monkeypatch.delenv("OPENFLOW_INSTANCE", raising=False)
    app, client = _client()
    assert client.get("/api/info/system").json()["instance"] is None
    assert client.post("/rpc/shutdown", json={"instance": ""}).status_code == 403
    assert app.state.server.should_exit is False
    print("  started by hand: no token, no remote shutdown")
