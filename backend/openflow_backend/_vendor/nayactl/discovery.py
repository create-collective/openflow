## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Device discovery: serial ports and ZMQ endpoints."""

from __future__ import annotations

import glob
import os

from serial.tools.list_ports import comports

from .constants import NAYA_VID, PID_NAMES, PID_LEFT, PID_RIGHT, PID_DONGLE
from .types import DeviceInfo


# PID -> side mapping
_PID_SIDE = {
  PID_LEFT:   "left",
  PID_RIGHT:  "right",
  PID_DONGLE: "dongle",
}


def find_naya_serial_ports() -> list[DeviceInfo]:
  """Scan for connected Naya Create devices by USB VID/PID."""
  devices = []
  for port_info in comports():
    if port_info.vid == NAYA_VID and port_info.pid in _PID_SIDE:
      devices.append(DeviceInfo(
        port=port_info.device,
        pid=port_info.pid,
        side=_PID_SIDE[port_info.pid],
        description=PID_NAMES.get(port_info.pid, "Unknown"),
        serial_number=port_info.serial_number or "",
      ))
  return devices


def find_naya_serial_port(side: str = "left") -> DeviceInfo | None:
  """Find a specific Naya device by side (left/right/dongle)."""
  for dev in find_naya_serial_ports():
    if dev.side == side:
      return dev
  return None


def find_zmq_ports() -> tuple[int, int] | None:
  """Try to discover NayaCore's ZMQ PUB/SUB ports.

  Checks POSIX shared memory (/dev/shm/) for Qt QSharedMemory keys,
  and /tmp/ for file-based fallback.

  Returns (core_pub_port, flow_pub_port) or None if not found.
  """
  core_port = _read_zmq_port("ZMQ_CORE_PUB_PORT_SHARED_MEM")
  flow_port = _read_zmq_port("ZMQ_FLOW_PUB_PORT_SHARED_MEM")
  if core_port and flow_port:
    return (core_port, flow_port)
  return None


def _read_zmq_port(key: str) -> int | None:
  """Read a ZMQ port number from Qt shared memory or temp file."""
  # Qt QSharedMemory on Linux uses /dev/shm/qipc_sharedmemory_<key>
  for pattern in [
    f"/dev/shm/qipc_sharedmemory_*{key}*",
    f"/tmp/{key}",
    f"/tmp/qipc_sharedmemory_*{key}*",
  ]:
    for path in glob.glob(pattern):
      try:
        data = open(path, "rb").read(64)
        # Port is typically stored as a small integer in the first bytes
        text = data.strip(b"\x00").decode("ascii", errors="ignore").strip()
        if text.isdigit():
          return int(text)
      except (OSError, ValueError):
        continue
  return None


def detect_nayacore_running() -> bool:
  """Check if a NayaCore process is currently running."""
  for pid_dir in glob.glob("/proc/[0-9]*/"):
    try:
      cmdline = open(os.path.join(pid_dir, "cmdline"), "rb").read()
      if b"NayaCore" in cmdline or b"nayacore" in cmdline:
        return True
    except OSError:
      continue
  return False
