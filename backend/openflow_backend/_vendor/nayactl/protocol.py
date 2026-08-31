## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""CDC binary protocol: message building and parsing."""

from .constants import SOURCE_HOST, EOT
from .types import CDCResponse


def xor_checksum(data: bytes) -> int:
  """XOR checksum over all bytes in data."""
  result = 0
  for b in data:
    result ^= b
  return result


def build_message(
  dest: int,
  category: int,
  subcmd: int,
  payload: bytes = b"",
  source: int = SOURCE_HOST,
) -> bytes:
  """Build a CDC binary message with correct wire framing.

  Wire format:
    [source, 0x00, dest, 0x00, category, data_size,
         subcmd_hi, subcmd_lo, flags, payload...,
         xor_checksum, 0x04]
  """
  subcmd_hi = (subcmd >> 8) & 0xFF
  subcmd_lo = subcmd & 0xFF
  flags = 0x00
  data_region = bytes([subcmd_hi, subcmd_lo, flags]) + payload
  data_size = len(data_region)
  trailer = xor_checksum(data_region)
  return (
    bytes([source, 0x00, dest, 0x00, category, data_size])
    + data_region
    + bytes([trailer, EOT])
  )


def parse_response(data: bytes) -> CDCResponse:
  """Parse a binary CDC response frame."""
  if len(data) < 11 or data[-1] != EOT:
    return CDCResponse(raw=data)

  source = data[0]
  category = data[4]
  data_size = data[5]
  subcmd = (data[6] << 8) | data[7]
  flags = data[8]

  payload_len = data_size - 3  # subtract subcmd(2) + flags(1)
  payload = data[9:9 + payload_len] if payload_len > 0 else b""

  # Verify checksum
  trailer_pos = 6 + data_size
  if trailer_pos < len(data):
    expected = xor_checksum(data[6:6 + data_size])
    checksum_ok = expected == data[trailer_pos]
  else:
    checksum_ok = False

  return CDCResponse(
    raw=data,
    valid=True,
    source=source,
    category=category,
    subcmd=subcmd,
    flags=flags,
    payload=payload,
    checksum_ok=checksum_ok,
  )


def build_text_command(cmd: str) -> bytes:
  """Build a SystemCDC text command with CRLF termination."""
  return (cmd.rstrip("\r\n") + "\r\n").encode("ascii")
