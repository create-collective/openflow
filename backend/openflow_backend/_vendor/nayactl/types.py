## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Data types for CDC protocol messages and device info."""

from dataclasses import dataclass, field


@dataclass
class CDCResponse:
  """Parsed binary CDC response."""
  raw: bytes
  valid: bool = False
  source: int = 0
  category: int = 0
  subcmd: int = 0
  flags: int = 0
  payload: bytes = b""
  checksum_ok: bool = False

  @property
  def payload_hex(self) -> str:
    return self.payload.hex() if self.payload else ""


@dataclass
class DeviceInfo:
  """Discovered Naya device on a serial port."""
  port: str
  pid: int
  side: str  # "left", "right", "dongle"
  description: str = ""
  serial_number: str = ""


@dataclass
class DeviceStatus:
  """Aggregated device status from multiple queries."""
  fw_version: str | None = None
  hw_id: bytes | None = None
  battery_level: int | None = None
  module_type: str | None = None
  module_fw_version: str | None = None
  module_battery: int | None = None
  module_connected: bool = False
