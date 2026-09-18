"""Linux permission to open the keyboard's serial ports (device/port_access.py).

Without OpenFlow's udev rule a normal Linux user cannot open /dev/ttyACM*, and the halves used to
read as merely "not connected". What is pinned here: the refusal is recognised only where the
udev advice is right (Linux, EACCES/EPERM), it reaches the live status and the full status with
the fix attached, the recovery path says the same, and the rule the app tells the user to
install is byte-for-byte the rule the .deb installs. No hardware.
"""
from __future__ import annotations

import errno
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import port_access, recovery, service as service_mod  # noqa: E402
from openflow_backend.device.service import DeviceService, TransportError  # noqa: E402

RULES_FILE = _BACKEND.parent / "build" / "linux" / port_access.RULE_FILE


def _refused_open(port="/dev/ttyACM0", code=errno.EACCES) -> TransportError:
    """What the vendored transport raises when pyserial cannot open the port: its
    TransportError("Cannot open ...") chained from pyserial's SerialException(errno, msg)."""
    cause = serial.SerialException(code, f"could not open port {port}: [Errno {code}] {port}")
    try:
        try:
            raise cause
        except serial.SerialException as e:
            raise TransportError(f"Cannot open {port}: {e}") from e
    except TransportError as e:
        return e


# --- the rule ----------------------------------------------------------------------------------

def test_the_in_app_rule_is_the_packaged_rule():
    """The .deb installs build/linux/70-openflow.rules; the AppImage user pastes RULE_LINES. They
    must grant the same thing, or one of the two installs quietly does less."""
    packaged = [ln for ln in RULES_FILE.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]
    assert packaged == list(port_access.RULE_LINES)


def test_the_rule_covers_the_whole_vendor_and_keeps_modemmanager_off():
    joined = "\n".join(port_access.RULE_LINES)
    assert 'ATTRS{idVendor}=="37d1"' in port_access.RULE_LINES[0]
    assert 'ATTRS{idVendor}=="37d1"' in port_access.RULE_LINES[1]
    assert "idProduct" not in joined, "matching on vendor only is what covers the bootloader pids"
    assert 'ENV{ID_MM_DEVICE_IGNORE}="1"' in joined
    assert 'TAG+="uaccess"' in joined
    assert int(port_access.RULE_FILE.split("-")[0]) < 73, "uaccess must be tagged before 73-seat-late"


def test_the_readme_gives_the_same_commands():
    """The README's Linux section is what a tester reads before the app ever runs."""
    readme = (_BACKEND.parent / "README.md").read_text(encoding="utf-8")
    assert port_access.INSTALL_COMMANDS in readme


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs a POSIX shell")
def test_the_pasted_command_writes_exactly_the_rule():
    """Run the printf half of the first command (everything before `| sudo tee`) through a real
    shell and compare what it would write with the rule."""
    first = port_access.INSTALL_COMMANDS.splitlines()[0]
    printf_part, tee_part = first.split(" | ", 1)
    assert tee_part == f"sudo tee /etc/udev/rules.d/{port_access.RULE_FILE} >/dev/null"
    out = subprocess.run(["bash", "-c", printf_part], capture_output=True, check=True).stdout
    assert out.decode().splitlines() == list(port_access.RULE_LINES)


# --- recognising the refusal -------------------------------------------------------------------

@pytest.mark.parametrize("code", [errno.EACCES, errno.EPERM])
def test_a_refused_open_on_linux_is_recognised(code):
    assert port_access.is_permission_denied(_refused_open(code=code), platform="linux")


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_only_on_linux(platform):
    """On Windows a refused COM port means another program holds it; udev advice would be wrong."""
    assert not port_access.is_permission_denied(_refused_open(), platform=platform)


@pytest.mark.parametrize("code", [errno.ENOENT, errno.EBUSY, errno.EIO])
def test_other_open_failures_are_not_permission(code):
    assert not port_access.is_permission_denied(_refused_open(code=code), platform="linux")


def test_nothing_is_not_permission():
    assert not port_access.is_permission_denied(None, platform="linux")


# --- the service ------------------------------------------------------------------------------

class _RefusingTransport:
    """Stands in for SerialTransport on a port Linux will not let us open."""

    def __init__(self, port, dest):
        self.port = port
        self.is_connected = False

    def connect(self):
        raise _refused_open(self.port)

    def disconnect(self):
        pass


@pytest.fixture
def linux_refusing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(service_mod, "SerialTransport", _RefusingTransport)
    dev = SimpleNamespace(port="/dev/ttyACM0", side="left", pid=0x0064,
                          description="Create Left", serial_number="X")
    monkeypatch.setattr(service_mod, "find_naya_serial_ports", lambda: [dev])
    return dev


def test_opening_a_refused_port_raises_the_fix(linux_refusing):
    svc = DeviceService()
    with pytest.raises(port_access.PortAccessDenied) as ei:
        svc._transport_for("/dev/ttyACM0", 0)
    assert isinstance(ei.value, TransportError), "every existing TransportError handler still applies"
    assert "udev rule" in str(ei.value) and "/dev/ttyACM0" in str(ei.value)
    assert ei.value.fix == port_access.fix_for("/dev/ttyACM0")
    assert svc._transports == {}, "a port that never opened is not cached"


def test_the_live_status_carries_the_fix(linux_refusing):
    svc = DeviceService()
    snap = svc.tick_all()
    half = snap["halves"][0]
    assert half["connected"] is False
    assert half["fix"]["kind"] == "linux-udev-rule"
    assert half["fix"]["commands"] == port_access.INSTALL_COMMANDS
    assert "udev rule" in half["error"]


def test_the_full_status_carries_the_fix(linux_refusing):
    entry = DeviceService().status_all()[0]
    assert entry["connected"] is False
    assert entry["fix"]["kind"] == "linux-udev-rule"


def test_an_ordinary_disconnect_has_no_fix():
    svc = DeviceService()
    snap = svc._mark_disconnected("left", None, "no longer on the USB bus")
    assert "fix" not in snap


def test_windows_refusals_keep_their_own_message(monkeypatch, linux_refusing):
    """Same refusal on Windows: the vendored "Cannot open" error, untouched, and no fix."""
    monkeypatch.setattr(sys, "platform", "win32")
    half = DeviceService().tick_all()["halves"][0]
    assert half["error"].startswith("Cannot open")
    assert "fix" not in half


# --- recovery ----------------------------------------------------------------------------------

def test_recovery_says_the_same(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def refuse(*a, **k):
        raise serial.SerialException(errno.EACCES, "could not open port /dev/ttyACM2: [Errno 13]")

    monkeypatch.setattr(serial, "Serial", refuse)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(serial.SerialException) as ei:
        recovery._talk("/dev/ttyACM2", b"\x00")
    assert "udev rule" in str(ei.value) and "/dev/ttyACM2" in str(ei.value)
