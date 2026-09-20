"""A cached serial transport that died under the backend must not poison every later call.

Seen 2026-09-10: the board was power-cycled while the backend held COM9 open. pyserial still
said the port was open, so `_transport_for` kept handing out the dead handle, and every LED /
read / flash call answered "Write to COM9 failed: WriteFile failed (PermissionError(13, 'The
device does not recognize the command.'))" until the backend was restarted. Discovery already
dropped a dead transport on error; the RPC paths did not. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))


from openflow_backend.device import service as S                # noqa: E402

DEAD = "Write to COM9 failed: WriteFile failed (PermissionError(13, 'The device does not recognize the command.', None, 22))"
TIMEOUT = "No response from device on COM9 (timeout 2.5s)"


class FakeTransport:
    """Stands in for SerialTransport. `fail_with` makes the FIRST command raise."""
    instances: list["FakeTransport"] = []
    fail_next: list[str] = []          # consumed by each new instance's first send

    def __init__(self, port, dest):
        self.port, self.dest = port, dest
        self.sent = []
        self.connected = False
        self.disconnected = False
        self._fail = FakeTransport.fail_next.pop(0) if FakeTransport.fail_next else None
        FakeTransport.instances.append(self)

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected = True
        self.connected = False

    @property
    def is_connected(self):
        return self.connected

    def _send(self, what):
        if self._fail:
            msg, self._fail = self._fail, None
            raise S.TransportError(msg)
        self.sent.append(what)
        return []

    def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
        return self._send(("cmd", category, subcmd, bytes(payload)))

    def send_text(self, command, allow_dangerous=False):
        self._send(("text", command))
        return "ok"


class Dev:
    port, side = "COM9", "left"


@pytest.fixture
def svc(monkeypatch):
    FakeTransport.instances.clear()
    FakeTransport.fail_next.clear()
    monkeypatch.setattr(S, "SerialTransport", FakeTransport)
    s = S.DeviceService()
    monkeypatch.setattr(s, "_require_side", lambda side, serial=None: Dev())
    return s


def test_a_dead_cached_handle_is_replaced_and_the_command_still_lands(svc):
    FakeTransport.fail_next.append(DEAD)
    out = svc.led("left", "effect", 1)
    assert out["ok"] is True
    first, second = FakeTransport.instances
    assert first.disconnected and first.sent == [], "the dead handle sent nothing and was dropped"
    assert second.sent == [("cmd", S.C.CAT_LED, S.C.LED_SELECT_EFFECT, bytes([0, 1]))]
    assert svc._transports["COM9"] is second, "the fresh handle is the cached one now"


def test_a_timeout_is_not_retried():
    """A timed-out command may have landed. Re-sending it is not the transport layer's call."""
    # separate fixture-less setup so the assertion about instance count is exact
    FakeTransport.instances.clear(); FakeTransport.fail_next.clear()
    FakeTransport.fail_next.append(TIMEOUT)
    import openflow_backend.device.service as S2
    orig = S2.SerialTransport
    S2.SerialTransport = FakeTransport
    try:
        s = S2.DeviceService(); s._require_side = lambda side, serial=None: Dev()
        with pytest.raises(S.TransportError, match="No response"):
            s.led("left", "effect", 1)
        assert len(FakeTransport.instances) == 1
        assert not FakeTransport.instances[0].disconnected
    finally:
        S2.SerialTransport = orig


def test_the_retry_is_one_deep(svc):
    """Two dead handles in a row means the port really is gone; say so instead of looping."""
    FakeTransport.fail_next.extend([DEAD, DEAD])
    with pytest.raises(S.TransportError, match="Write to COM9 failed"):
        svc.led("left", "on")
    assert len(FakeTransport.instances) == 2


def test_every_rpc_path_goes_through_the_retry(svc):
    """text_command, read_keymap, read_module_configs, spi_flash_test and keyscan all used to
    fetch the transport by hand. They must all recover the same way led does."""
    FakeTransport.fail_next.append(DEAD)
    assert svc.text_command("left", "dump_settings")["reply"] == "ok"
    assert len(FakeTransport.instances) == 2 and FakeTransport.instances[0].disconnected

    for name in ("read_keymap", "read_module_configs", "spi_flash_test", "keyscan"):
        src = Path(S.__file__).read_text(encoding="utf-8")
        body = src.split(f"def {name}(")[1].split("\n    def ")[0]
        assert "_with_transport" in body, f"{name} bypasses the retry"
        assert "self._transport_for(" not in body, f"{name} still fetches the transport by hand"


def test_a_handle_whose_status_query_fails_is_not_handed_out(svc):
    """The cheap check: a dead Windows CDC handle rejects ClearCommError, which pyserial surfaces
    from `in_waiting`. Such a transport is replaced before any command is attempted."""
    class DeadSerial:
        @property
        def in_waiting(self):
            raise OSError("ClearCommError failed (PermissionError(13, ...))")

    stale = FakeTransport("COM9", 0x50); stale.connected = True; stale._ser = DeadSerial()
    svc._transports["COM9"] = stale
    svc.led("left", "on")
    assert stale.disconnected and stale.sent == []
    assert svc._transports["COM9"] is not stale


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
