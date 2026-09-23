"""The firmware endpoints are off unless the environment turns them on.

The gate used to be a hardcoded `False` that a test would edit to True. That is one forgotten
revert away from shipping a build whose firmware endpoint is live, so it reads the environment
instead: enabling it is a property of the session doing the flashing, and cannot be committed.

What is pinned here is the DEFAULT and the exact truthiness, because "anything set means on" is
how an unrelated `OPENFLOW_ENABLE_FIRMWARE_FLASH=0` in someone's shell would arm it.
"""
import importlib

import pytest

from openflow_backend.api import rest


VAR = "OPENFLOW_ENABLE_FIRMWARE_FLASH"


def gate_with(monkeypatch, value):
    """Re-import the module with the variable set as given; the gate is read at import."""
    if value is None:
        monkeypatch.delenv(VAR, raising=False)
    else:
        monkeypatch.setenv(VAR, value)
    return importlib.reload(rest).FIRMWARE_FLASH_ENABLED


@pytest.fixture(autouse=True)
def _restore():
    """Leave the module as the rest of the suite expects to find it."""
    yield
    import os
    os.environ.pop(VAR, None)
    importlib.reload(rest)


def test_the_gate_is_off_when_nothing_is_set(monkeypatch):
    assert gate_with(monkeypatch, None) is False


@pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "true", "TRUE", "yes", "2"])
def test_only_the_exact_value_one_opens_it(monkeypatch, value):
    """Deliberately strict. A stray 0 or 'false' in a shell must not arm a firmware write, and
    neither should a well-meaning 'true' that was never the documented value."""
    assert gate_with(monkeypatch, value) is False


def test_one_opens_it(monkeypatch):
    assert gate_with(monkeypatch, "1") is True


def test_the_endpoint_refuses_while_the_gate_is_shut(monkeypatch):
    """The refusal must come BEFORE anything reaches the upload path."""
    monkeypatch.delenv(VAR, raising=False)
    mod = importlib.reload(rest)
    assert mod.FIRMWARE_FLASH_ENABLED is False

    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from openflow_backend.app import create_app

    with TestClient(create_app()) as c:
        for route in ("/rpc/flash-firmware", "/rpc/flash-module-firmware"):
            r = c.post(route, json={"image": "kb_fwl.bin", "arm": "x"})
            assert r.status_code == 400, route
            assert "Nothing was sent" in r.json()["detail"], route
        # The supervised procedure (SCRUM-108) is the path a USER reaches, so it is the one that
        # most needs the gate. It must refuse before a backup is taken, let alone a byte written.
        r = c.post("/rpc/flash-procedure",
                   json={"targets": {"left": "kb_fwl.bin", "right": "kb_fwr.bin"}})
        assert r.status_code == 400
        assert "Nothing was sent" in r.json()["detail"]
        # Its module twin (2026-09-23) is reached the same way and refuses the same way.
        r = c.post("/rpc/module-flash-procedure", json={"force_upload": True})
        assert r.status_code == 400
        assert "Nothing was sent" in r.json()["detail"]
    assert HTTPException  # imported for the reader: the refusal is an HTTP 400, not a crash


def test_the_procedure_validates_its_targets_before_the_gate_is_ever_relevant(monkeypatch):
    """An empty or malformed target set is refused as a bad request, not as a gate failure, so
    the message a developer gets says what is actually wrong."""
    monkeypatch.setenv(VAR, "1")
    importlib.reload(rest)
    from fastapi.testclient import TestClient
    from openflow_backend.app import create_app

    with TestClient(create_app()) as c:
        for body in ({}, {"targets": {}}, {"targets": {"middle": "x.bin"}}):
            r = c.post("/rpc/flash-procedure", json=body)
            assert r.status_code == 400, body
            assert "Nothing was sent" not in r.json()["detail"], body
