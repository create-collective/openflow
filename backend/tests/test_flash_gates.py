"""The /rpc/flash gates. This is the only endpoint that changes the keyboard.

Two modes with different promises:
  sync     -- reads the board first and plans against it, so everything the app does not model
              (module->dock bindings, TRANS records, second-bank positions) is carried through.
  recovery -- for a board that can no longer be read. Nothing can be preserved, so it must be
              asked for explicitly and separately from the ordinary confirm.
No hardware: these exercise the request guards, not the write.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openflow_backend.api import rest  # noqa: E402

app = FastAPI()
app.include_router(rest.router)
client = TestClient(app)

BODY = {"confirm": "FLASH", "profileId": "whatever"}


def _post(**kw):
    return client.post("/rpc/flash", json={**BODY, **kw})


def test_refuses_without_the_confirm_token():
    r = client.post("/rpc/flash", json={"profileId": "x"})
    assert r.status_code == 400 and "confirm" in r.text
    for bad in ("flash", "yes", "", "Flash"):
        assert client.post("/rpc/flash", json={"confirm": bad}).status_code == 400
    print("  a stray POST, or a near-miss token, cannot write")


def test_refuses_an_unknown_mode():
    r = _post(mode="yolo")
    assert r.status_code == 400 and "sync|recovery" in r.text
    print("  unknown modes are refused rather than falling through to a default")


def test_recovery_needs_its_own_acknowledgement():
    r = _post(mode="recovery")
    assert r.status_code == 400, "recovery proceeded on the ordinary confirm alone"
    for word in ("module-to-dock", "overwritten"):
        assert word in r.text, f"the refusal must say what is lost: missing {word!r}"
    assert _post(mode="recovery", acknowledgeRecovery="yes").status_code == 400
    assert _post(mode="recovery", acknowledgeRecovery=1).status_code == 400
    print("  recovery needs acknowledgeRecovery=true exactly, and says what it destroys")


def test_gate_order_confirm_before_anything_else():
    r = client.post("/rpc/flash", json={"mode": "recovery", "acknowledgeRecovery": True})
    assert r.status_code == 400 and "confirm" in r.text
    print("  the confirm gate is checked first")


if __name__ == "__main__":
    for fn in (test_refuses_without_the_confirm_token,
               test_refuses_an_unknown_mode,
               test_recovery_needs_its_own_acknowledgement,
               test_gate_order_confirm_before_anything_else):
        print(fn.__name__)
        fn()
    print("\nOK")
