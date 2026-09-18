"""Releasing the keyboard: OpenFlow lets go of the serial ports so other software can have it.

OpenFlow holds both CDC ports open for as long as it runs, which is why using NayaFlow meant
quitting OpenFlow. Release closes them and stands the poll down; reconnect takes them back.
What is pinned here is that released really does mean HANDS OFF -- no port is opened, by the
poll or by anything else -- and that it is a decision, not a device state, so it survives until
it is reversed. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device.service import DeviceService, TransportError  # noqa: E402


class _FakeTransport:
    def __init__(self):
        self.disconnected = False
        self.is_connected = True

    def disconnect(self):
        self.disconnected = True
        self.is_connected = False


def _svc_holding_a_port():
    """A service that believes it holds COM6 for a connected left half."""
    svc = DeviceService()
    t = _FakeTransport()
    svc._transports["COM6"] = t
    svc._live["left"] = {"side": "left", "port": "COM6", "connected": True, "batteryPercent": 88}
    return svc, t


def test_release_closes_the_port_and_says_so():
    svc, t = _svc_holding_a_port()
    assert svc.released is False
    assert svc.release() == {"released": True}
    assert svc.released is True
    assert t.disconnected, "release must actually close the handle, not just set a flag"
    assert svc._transports == {}, "a released service holds no transports"
    print("  release closes the handle and drops it")


def test_a_released_half_is_not_reported_as_connected():
    """Another application may be flashing it; claiming a connection would be a lie."""
    svc, _ = _svc_holding_a_port()
    svc.release()
    snap = svc.snapshot()
    half = snap["halves"][0]
    assert snap["released"] is True
    assert half["connected"] is False
    assert half["error"] == DeviceService.RELEASED_REASON
    print("  a released half reads as not connected, with the reason saying why")


def test_nothing_opens_a_port_while_released():
    svc, _ = _svc_holding_a_port()
    svc.release()
    with pytest.raises(TransportError) as e:
        svc._transport_for("COM6", 0x50)
    assert "released" in str(e.value)
    print("  opening a port while released is refused, with a reason a person can act on")


def test_the_poll_stands_down_while_released(monkeypatch):
    """The 6 s poll is what would otherwise grab the port straight back."""
    svc, _ = _svc_holding_a_port()
    called = []
    monkeypatch.setattr("openflow_backend.device.service.find_naya_serial_ports",
                        lambda: called.append(1) or [])
    svc.release()
    svc.tick_all()
    assert called == [], "the poll must not even enumerate while released"
    svc.reconnect()
    svc.tick_all()
    assert called == [1], "reconnect puts the poll back to work"
    print("  the poll stands down while released and resumes on reconnect")


def test_reconnect_is_the_only_way_back():
    svc, _ = _svc_holding_a_port()
    svc.release()
    assert svc.snapshot()["released"] is True
    # A snapshot, a tick, or another release must not quietly undo it.
    svc.tick_all()
    svc.release()
    assert svc.released is True
    assert svc.reconnect() == {"released": False}
    assert svc.released is False
    print("  released persists until reconnect; nothing else clears it")
