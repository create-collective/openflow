## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Formatting and output helpers."""

from .constants import CAT_NAMES, SUBCMD_NAMES


def hexdump(data: bytes, prefix: str = "") -> str:
  """Format bytes as a hex dump with ASCII sidebar."""
  lines = []
  for i in range(0, len(data), 16):
    chunk = data[i:i + 16]
    hex_part = " ".join(f"{b:02x}" for b in chunk)
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    lines.append(f"{prefix}{i:04x}  {hex_part:<48s}  |{ascii_part}|")
  return "\n".join(lines)


def hexline(data: bytes) -> str:
  """Format bytes as a single hex string."""
  return " ".join(f"{b:02x}" for b in data) if data else "(empty)"


def format_fw_version(payload: bytes) -> str:
  """Format firmware version payload as dotted string.

  Response payloads often have leading status/padding bytes.
  KB FW: [0x00, major, minor, patch] → "major.minor.patch"
  Module FW: [status, 0x00, 0x00, major, minor, patch] → "major.minor.patch"

  We strip all leading zero bytes, and if the first byte is non-zero
  but the rest looks like a version (small values), we skip it as a status byte.
  """
  if not payload:
    return "unknown"

  # Strip leading zero bytes
  stripped = payload.lstrip(b'\x00')
  if not stripped:
    return "0"

  # If original had a non-zero first byte followed by zeros then version bytes,
  # it's likely [status, padding..., version...]. Check if first byte looks
  # like a status (>= 0x10) while remaining bytes are small version numbers.
  if (len(payload) > 3 and payload[0] >= 0x10
      and all(b < 100 for b in payload[-3:])):
    # Use last 3 bytes as major.minor.patch
    return ".".join(str(b) for b in payload[-3:])

  # Otherwise strip leading zeros
  return ".".join(str(b) for b in stripped)


def format_category(cat: int) -> str:
  """Format a category byte as name or hex."""
  return CAT_NAMES.get(cat, f"0x{cat:02x}")


def format_subcmd(cat: int, subcmd: int) -> str:
  """Format a subcmd as name or hex, within its category."""
  names = SUBCMD_NAMES.get(cat, {})
  name = names.get(subcmd)
  if name:
    return f"{name} (0x{subcmd:04x})"
  return f"0x{subcmd:04x}"
