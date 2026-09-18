"""Linux: permission to open the keyboard's serial ports, and what to tell the user without it.

Each half of the Create (and a half in its recovery bootloader) is a USB CDC serial port,
/dev/ttyACM*, which on Linux belongs to root and the dialout group. A normal user's OpenFlow
enumerates the halves fine -- enumeration reads sysfs -- and then fails to open them with
EACCES, which used to surface as a half that is simply "not connected". Here that one failure
is recognised and turned into the fix: a udev rule, the same one the .deb installs
(build/linux/70-openflow.rules), with the commands to install it by hand for the AppImage.

Only Linux. On Windows a permission error opening a COM port means ANOTHER PROGRAM HOLDS IT
(error 5, "Access is denied"), and the udev advice would be wrong; macOS lets the user open
/dev/cu.* without help.
"""
from __future__ import annotations

import errno
import sys

from .._vendor.nayactl.transport import TransportError

RULE_FILE = "70-openflow.rules"

# The two rule lines of build/linux/70-openflow.rules, verbatim. tests/test_port_access.py holds
# them equal to the packaged file, so the .deb and the in-app fix never grant different things.
RULE_LINES = (
    'ACTION!="remove", SUBSYSTEMS=="usb", ATTRS{idVendor}=="37d1", ENV{ID_MM_DEVICE_IGNORE}="1"',
    'ACTION!="remove", SUBSYSTEM=="tty", ATTRS{idVendor}=="37d1", TAG+="uaccess"',
)

# printf rather than a heredoc: it pastes the same into bash, zsh and fish. The rule lines hold
# double quotes and "!", both inert inside single quotes in all three.
INSTALL_COMMANDS = "\n".join((
    "printf '%s\\n' " + " ".join(f"'{line}'" for line in RULE_LINES)
    + f" | sudo tee /etc/udev/rules.d/{RULE_FILE} >/dev/null",
    "sudo udevadm control --reload-rules",
    "sudo udevadm trigger --subsystem-match=tty",
))

_DENIED = (errno.EACCES, errno.EPERM)


def is_permission_denied(exc: BaseException | None, platform: str | None = None) -> bool:
    """True when opening a port failed because Linux refused the user access to it.

    pyserial raises SerialException(errno, message) for a failed open, and the vendored
    transport re-raises that as TransportError("Cannot open ...") from it, so the errno is one
    or two links down the cause chain rather than on the exception in hand."""
    if not (platform or sys.platform).startswith("linux"):
        return False
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in _DENIED:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def fix_for(port: str) -> dict:
    """What the page shows: machine-readable, so the renderer can lay it out and copy it."""
    return {
        "kind": "linux-udev-rule",
        "port": port,
        "ruleFile": RULE_FILE,
        "commands": INSTALL_COMMANDS,
    }


def denied_message(port: str) -> str:
    return (f"Linux denied access to {port}. The keyboard's serial ports belong to root and the "
            f"dialout group; install OpenFlow's udev rule ({RULE_FILE}) so you can use them. "
            "The Hub page has the commands.")


class PortAccessDenied(TransportError):
    """Opening a half's port failed for lack of permission (Linux). Still a TransportError, so
    every caller that already handles a port that will not open handles this one; the message
    says what to do, and `fix` carries it structured for the status the page renders."""

    def __init__(self, port: str):
        super().__init__(denied_message(port))
        self.port = port
        self.fix = fix_for(port)
