## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Module command group."""

from __future__ import annotations

import click

from ..constants import CAT_MODULE, MOD_DETECT, MOD_GET_BATTERY, MOD_GET_FW_VERSION, MOD_GET_PRECISE_BATTERY, MOD_SEND_HANDSHAKE
from ..util import format_fw_version, hexline
from .context import TransportContext, pass_ctx


def register(cli: click.Group) -> None:
  """Register module command group."""

  @click.group()
  def module() -> None:
    """Module commands (Touch/Track/Tune)."""

  @module.command("info")
  @pass_ctx
  def module_info(tctx: TransportContext) -> None:
    """Query module: handshake, detect, FW version, battery."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)

    click.echo("Module handshake...")
    responses = transport.send_command(dest, CAT_MODULE, MOD_SEND_HANDSHAKE, timeout=2.0)
    for response in responses:
      if response.valid:
        click.echo(f"  Handshake: {hexline(response.payload)}")

    click.echo("Module detect...")
    responses = transport.send_command(dest, CAT_MODULE, MOD_DETECT, timeout=2.0)
    for response in responses:
      if response.valid:
        click.echo(f"  Detect:    {hexline(response.payload)}")

    click.echo("Module FW version...")
    responses = transport.send_command(dest, CAT_MODULE, MOD_GET_FW_VERSION, timeout=2.0)
    for response in responses:
      if response.valid:
        click.echo(f"  Firmware:  {format_fw_version(response.payload)}")

    click.echo("Module battery...")
    responses = transport.send_command(dest, CAT_MODULE, MOD_GET_BATTERY, timeout=2.0)
    for response in responses:
      if response.valid and response.payload:
        click.echo(f"  Battery:   {hexline(response.payload)}")

  @module.command("battery")
  @pass_ctx
  def module_battery(tctx: TransportContext) -> None:
    """Get precise module battery level."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    responses = transport.send_command(dest, CAT_MODULE, MOD_GET_PRECISE_BATTERY, timeout=2.0)
    for response in responses:
      if response.valid and response.payload:
        click.echo(f"  Precise battery: {hexline(response.payload)}")
    if not responses:
      click.echo("  No response")

  @module.command("status")
  @pass_ctx
  def module_status(tctx: TransportContext) -> None:
    """Query module status via text command."""
    transport = tctx.transport
    result = transport.send_text("c_module_status")
    if result:
      click.echo(result.strip())
    else:
      click.echo("No response")

  cli.add_command(module)
