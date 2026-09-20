"""The flash holds the service lock for its whole duration.

The live-status tick (service.tick, every ~6 s per half) runs under the service lock; the flash
route's reads did too, but the write between them drove the transport unlocked, so a tick could
put four commands on the port between two frames of a chunked write. On 2026-09-16 that cost a
flash its "led 0" continuation-frame ack (ack None) and it aborted. No hardware: the write is
faked and asserts that the lock is held and that another thread cannot take it meanwhile.
"""
from __future__ import annotations

import sys
import threading
import types
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from fastapi import FastAPI                        # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

from openflow_backend.api import rest              # noqa: E402
from openflow_backend.device import flash as F     # noqa: E402

app = FastAPI()
app.include_router(rest.router)
client = TestClient(app)


class FakeService:
    def __init__(self):
        self._lock = threading.RLock()
        self.calls = []

    def read_keymap(self, side, serial=None):
        self.calls.append("read_keymap")
        return {"layers": {}, "led": {}, "layer_uuids": {}}

    def read_module_configs(self, side, serial=None):
        return None                                # no module list: no layout, no follow-up read

    def _require_side(self, side, serial=None):
        return types.SimpleNamespace(port="COM0", side=side)

    def _dest_for_side(self, side):
        return 0x50

    def _transport_for(self, port, dest):
        return object()

    def list_devices(self):
        return []


class DummyConn:
    def close(self): pass


def test_the_write_runs_with_the_service_lock_held_and_a_tick_would_wait():
    svc = FakeService()
    seen = {}

    def fake_flash(desired, **kw):
        seen["owned"] = svc._lock._is_owned()
        # A tick trying to take the lock from its own thread must not get it while we write.
        got = []
        t = threading.Thread(target=lambda: got.append(svc._lock.acquire(timeout=0.2)))
        t.start(); t.join()
        if got and got[0]:
            svc._lock.release()
        seen["tick_could_enter"] = bool(got and got[0])
        return {"status": "sent-unverified"}

    with mock.patch.object(rest, "get_service", lambda: svc), \
         mock.patch.object(rest, "db_connect", lambda: DummyConn()), \
         mock.patch.object(F, "desired_from_db", lambda conn, pid: F.DesiredState(profile_id="p")), \
         mock.patch.object(F, "desired_from_device_read", lambda before: None), \
         mock.patch.object(F, "flash", fake_flash), \
         mock.patch.object(rest.dstate, "clear", lambda reason: None):
        r = client.post("/rpc/flash", json={"confirm": "FLASH", "profileId": "p"})
    assert r.status_code == 200, r.text
    assert seen["owned"] is True, "the flash must hold the service lock while it writes"
    assert seen["tick_could_enter"] is False, "a tick must wait behind the flash, not interleave"
    assert "read_keymap" in svc.calls, "the preservation read still happens (RLock re-entry)"
    print("  the flash holds the lock; a concurrent tick cannot enter")
