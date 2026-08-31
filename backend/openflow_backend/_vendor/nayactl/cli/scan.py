## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Scan command."""

from __future__ import annotations

import click

from ..discovery import find_naya_serial_ports


def register(cli: click.Group) -> None:
  """Register scan command."""

  @cli.command()
  def scan() -> None:
    """Scan for connected Naya devices."""
    devices = find_naya_serial_ports()
    if not devices:
      click.echo("No Naya Create devices found.")
      return
    for device in devices:
      click.echo(f"  {device.description:<15s}  {device.port}  (PID 0x{device.pid:04x})")
