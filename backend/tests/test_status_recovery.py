"""/api/status reports a half in recovery only when it is still there on a second look (SCRUM-88).

Every half passes through MCUboot for ~1.7 s on an ordinary power-on. The Troubleshooting page's
Read is the one place that shows "in recovery", and a click landing in that window used to show a
healthy, booting keyboard as stuck. The settle interval itself is pinned in test_recovery_smp;
here it is zero so the route is tested without a real wait. No hardware.
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
from openflow_backend.device import recovery as rec  # noqa: E402

RIGHT_IN_MCUBOOT = rec.RecoveryDevice(port="COM17", pid=0x00D3, side="right", generation="A")


def _client(monkeypatch, *scans):
    it = iter(scans)
    last = [[]]

    def find():
        last[0] = next(it, last[0])
        return last[0]
    svc = types.SimpleNamespace(status_all=lambda verbose=False: [], released=False)
    monkeypatch.setattr(rest, "get_service", lambda: svc)
    monkeypatch.setattr(rec, "find_recovery_ports", find)
    real = rec.still_in_recovery
    monkeypatch.setattr(rec, "still_in_recovery", lambda seen, at: real(seen, at, settle=0.0))
    app = FastAPI()
    app.include_router(rest.router)
    return TestClient(app)


def test_a_half_passing_through_the_bootloader_is_not_reported(monkeypatch):
    c = _client(monkeypatch, [RIGHT_IN_MCUBOOT], [])
    assert "recovery" not in c.get("/api/status").json()


def test_a_half_that_stays_is_reported(monkeypatch):
    c = _client(monkeypatch, [RIGHT_IN_MCUBOOT], [RIGHT_IN_MCUBOOT])
    got = c.get("/api/status").json()["recovery"]
    assert got == [{"port": "COM17", "description": "", "pid": 0x00D3, "side": "right",
                    "generation": "A"}]
