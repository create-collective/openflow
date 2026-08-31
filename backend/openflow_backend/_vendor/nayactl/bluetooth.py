## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Parsers for bluetooth command responses."""

from __future__ import annotations

from dataclasses import dataclass, field


def _mac(data: bytes) -> str:
  """Format 6 bytes as a MAC address."""
  return ":".join(f"{b:02X}" for b in data[:6])


@dataclass
class BLEProfile:
  """One BLE profile/pairing slot.

  Parsed from a 37-byte (0x25) profile struct in GET_BLE_STATUS payload.
  Wire offset 0 = profileIndex, then flags byte, then peer info + metrics.
  """
  profile_index: int = 0
  configured: bool = False
  bonded: bool = False
  connected: bool = False
  active: bool = False
  has_peer_addr: bool = False
  encrypted: bool = False
  authenticated: bool = False
  security_level: int = 0
  connection_mode: int = 0
  peer_address: str = ""
  peer_address_type: int = 0
  connection_interval: int = 0
  connection_latency: int = 0
  connection_timeout: int = 0
  phy_tx: int = 0
  phy_rx: int = 0
  phy_tx_enabled: bool = False
  role: int = 0
  max_tx_octets: int = 0
  max_rx_octets: int = 0


@dataclass
class BLEStatus:
  """Full BLE status from GET_BLE_STATUS (≥239 byte payload, CreateLeft only)."""
  revision: int = 0
  profile_count: int = 0
  active_profile: int = 0
  advertising_status: bool = False
  host_connected: bool = False
  local_addr_valid: bool = False
  global_conn_mode: int = 0
  local_address_type: int = 0
  local_address: str = ""
  profiles: list[BLEProfile] = field(default_factory=list)
  last_disconnect_reason: int = 0
  packet_error_count: int = 0


def parse_ble_status(payload: bytes) -> BLEStatus | None:
  """Parse GET_BLE_STATUS (0xBE/0x100C) response payload.

  Format (from NayaCore):
    offset 0:   4 bytes BE → revision (uint32)
    offset 4:   byte → profile_count
    offset 5:   byte → active_profile
    offset 6:   byte (bitfield) → advertising_status, host_connected, local_addr_valid
    offset 7:   byte → global_conn_mode
    offset 8:   byte → local_address_type
    offset 9:   6 bytes → local_address (MAC)
    offset 15:  5 x 37-byte profile structs (185 bytes)
    offset 200: 76 bytes diagnostics block (parsed by FUN_14033b170)

  Minimum payload size: 239 bytes.
  """
  if len(payload) < 239:
    return None

  status = BLEStatus()
  status.revision = (payload[0] << 24) | (payload[1] << 16) | (payload[2] << 8) | payload[3]
  status.profile_count = payload[4]
  status.active_profile = payload[5]
  flags = payload[6]
  status.advertising_status = bool(flags & 0x01)
  status.host_connected = bool(flags & 0x02)
  status.local_addr_valid = bool(flags & 0x04)
  status.global_conn_mode = payload[7]
  status.local_address_type = payload[8]
  status.local_address = _mac(payload[9:15])

  for i in range(5):
    off = 15 + i * 37
    if off + 37 > len(payload):
      break
    status.profiles.append(_parse_profile(payload, off))

  diag_off = 200
  if diag_off + 39 <= len(payload):
    status.last_disconnect_reason = payload[diag_off + 0x20] if diag_off + 0x20 < len(payload) else 0
    if diag_off + 0x26 <= len(payload):
      o = diag_off + 0x22
      status.packet_error_count = (
        (payload[o] << 24) | (payload[o + 1] << 16) | (payload[o + 2] << 8) | payload[o + 3]
      )

  return status


def _parse_profile(payload: bytes, off: int) -> BLEProfile:
  """Parse a single 37-byte BLE profile struct."""
  profile = BLEProfile()
  profile.profile_index = payload[off + 0]
  flags = payload[off + 1]
  profile.configured = bool(flags & 0x01)
  profile.bonded = bool(flags & 0x02)
  profile.connected = bool(flags & 0x04)
  profile.active = bool(flags & 0x08)
  profile.has_peer_addr = bool(flags & 0x10)
  profile.encrypted = bool(flags & 0x20)
  profile.authenticated = bool(flags & 0x40)
  profile.security_level = payload[off + 2]
  profile.connection_mode = payload[off + 3]
  profile.peer_address = _mac(payload[off + 6:off + 12])

  m = off + 12
  if off + 12 + 22 <= len(payload):
    profile.connection_interval = (payload[m + 0] << 8) | payload[m + 1]
    profile.connection_latency = (payload[m + 2] << 8) | payload[m + 3]
    profile.connection_timeout = (payload[m + 4] << 8) | payload[m + 5]
    profile.phy_tx = payload[m + 6]
    profile.phy_rx = payload[m + 7]
    profile.phy_tx_enabled = bool(payload[m + 8] & 0x01)
    profile.role = (payload[m + 9] << 8) | payload[m + 10]
    profile.max_tx_octets = (payload[m + 11] << 8) | payload[m + 12]
    profile.max_rx_octets = (payload[m + 20] << 8) | payload[m + 21]
  return profile


def parse_ble_pairs(payload: bytes) -> list[str]:
  """Parse GET_ALL_PAIRS (0xBE/0x1005) response payload."""
  if len(payload) < 1:
    return []
  count = payload[0]
  pairs = []
  for i in range(count):
    off = 1 + i * 6
    if off + 6 > len(payload):
      break
    pairs.append(_mac(payload[off:off + 6]))
  return pairs
