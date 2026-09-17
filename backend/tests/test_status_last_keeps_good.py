"""/api/status remembers a reading that saw the keyboard and forgets none of it on an empty one.

The pages paint their module bays and the halves from /api/status/last. A status taken while
the port was busy (right after a keymap read) answers with no halves at all; persisting that
blanked the bays on every load until the next good read. No hardware.
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

GOOD = [
    {"side": "left", "connected": True, "module": {"type": "Tune", "docked": "left"}},
    {"side": "right", "connected": True, "module": {"type": "Touch", "docked": "right"}},
]


def _client(monkeypatch, readings):
    it = iter(readings)
    svc = types.SimpleNamespace(status_all=lambda verbose=False: next(it))
    monkeypatch.setattr(rest, "get_service", lambda: svc)
    monkeypatch.setattr(rest.recovery_mod, "find_recovery_ports", lambda: [])
    app = FastAPI()
    app.include_router(rest.router)
    return TestClient(app)


def test_empty_reading_keeps_the_last_good_status(monkeypatch):
    c = _client(monkeypatch, [GOOD, []])
    first = c.get("/api/status").json()
    assert [h["module"]["type"] for h in first["halves"]] == ["Tune", "Touch"]

    second = c.get("/api/status").json()
    assert second["halves"] == []            # the live answer is reported as it was
    assert second["at"]

    last = c.get("/api/status/last").json()  # ...but the cache still holds the good one
    assert [h["module"]["docked"] for h in last["halves"]] == ["left", "right"]
    assert last["at"] == first["at"]
