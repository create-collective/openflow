"""Every exchange with a connected keyboard is recorded, so a "flash failed" that actually landed
can be told apart from one that did not -- the gap NayaFlow's own log once filled for this owner.

The vendored transport is not modified: LoggingTransport wraps it and records each send. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[0].parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import device_log as dl   # noqa: E402


class Inner:
    """A stand-in transport with the real send signatures."""
    def __init__(self):
        self.sent = []
    def send_command(self, dest, category, subcmd, payload=b"", timeout=1.0, allow_dangerous=False):
        self.sent.append(("cmd", category, subcmd, bytes(payload)))
        return [type("R", (), {"valid": True, "checksum_ok": True})()]
    def send_text(self, command, timeout=3.0, allow_dangerous=False):
        self.sent.append(("text", command))
        return "reply-text"
    def _send_raw(self, data, timeout):
        self.sent.append(("raw", bytes(data)))
        return []
    def boom(self):
        raise RuntimeError("nope")


def _fresh():
    dl.clear()
    return dl.LoggingTransport(Inner(), "COM-TEST")


def test_a_command_is_recorded_and_still_reaches_the_inner_transport():
    t = _fresh()
    t.send_command(0x50, 0xED, 0x1008, bytes([0, 40]))
    assert t._inner.sent == [("cmd", 0xED, 0x1008, bytes([0, 40]))], "the real send still happened"
    log = dl.entries()
    assert len(log) == 1
    e = log[0]
    assert e["kind"] == "command" and e["port"] == "COM-TEST" and e["ok"]
    assert "LED" in e["detail"] and "0x1008" in e["detail"]


def test_forwarding_is_verbatim_a_four_arg_call_stays_four_args():
    """The wrapper must not widen a call -- callers pass four positionals and the inner signature
    varies. Forwarding *args verbatim is what keeps that working (it broke the fakes once)."""
    t = _fresh()
    t.send_command(0x50, 0xFE, 0x1001)      # three positionals, no payload
    assert t._inner.sent == [("cmd", 0xFE, 0x1001, b"")]


def test_text_and_raw_are_recorded():
    t = _fresh()
    t.send_text("dump_settings")
    t._send_raw(b"\xaa\x50\x00", 2.0)
    kinds = [e["kind"] for e in dl.entries()]
    assert kinds == ["text", "raw"]


def test_an_error_is_recorded_as_not_ok_and_re_raised():
    t = _fresh()
    class Boom(Inner):
        def send_command(self, *a, **k):
            raise RuntimeError("device gone")
    t = dl.LoggingTransport(Boom(), "COM-TEST")
    dl.clear()
    try:
        t.send_command(0x50, 0xED, 0x1008, b"")
        assert False, "should have re-raised"
    except RuntimeError:
        pass
    e = dl.entries()[-1]
    assert e["ok"] is False and "device gone" in e["detail"]


def test_the_buffer_is_bounded():
    dl.clear()
    t = dl.LoggingTransport(Inner(), "COM-TEST")
    for _ in range(dl._MAX + 50):
        t.send_command(0x50, 0xED, 0x1008, b"")
    assert len(dl.entries(10000)) == dl._MAX


def test_getattr_delegates_to_the_inner_transport():
    """Everything not a send path falls through -- the liveness check reads _ser, is_connected."""
    inner = Inner(); inner.is_connected = True; inner._ser = object()
    t = dl.LoggingTransport(inner, "COM-TEST")
    assert t.is_connected is True and t._ser is inner._ser


def test_entries_are_appended_to_a_daily_file_and_old_ones_pruned(tmp_path, monkeypatch):
    """The log must survive to a file (a keyboard sits plugged in for months), rotated per day and
    pruned past the retention window so it cannot grow without bound."""
    import time
    from openflow_backend import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    dl._pruned = False
    # a stale log file from 30 days ago must be pruned
    old = (tmp_path / "logs"); old.mkdir(parents=True, exist_ok=True)
    stale = old / "device-2000-01-01.log"; stale.write_text("old\n", encoding="utf-8")
    import os
    os.utime(stale, (time.time() - 30 * 86400, time.time() - 30 * 86400))

    t = dl.LoggingTransport(Inner(), "COM-TEST")
    dl.clear()
    t.send_command(0x50, 0xED, 0x1008, bytes([0, 40]))

    files = list((tmp_path / "logs").glob("device-*.log"))
    assert not stale.exists(), "a log older than the retention window is pruned"
    today = [f for f in files if f.name != "device-2000-01-01.log"]
    assert len(today) == 1, today
    assert "LED" in today[0].read_text(encoding="utf-8")


def test_a_logging_failure_never_breaks_device_io(tmp_path, monkeypatch):
    """If the log file cannot be written, the send must still happen -- logging is never load-bearing."""
    from openflow_backend import config
    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(config, "logs_dir", boom, raising=False)
    dl._pruned = False
    t = dl.LoggingTransport(Inner(), "COM-TEST")
    dl.clear()
    t.send_command(0x50, 0xED, 0x1008, b"")     # must not raise
    assert t._inner.sent, "the command still reached the device despite the log write failing"
