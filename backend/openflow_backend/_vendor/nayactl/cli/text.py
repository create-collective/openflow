## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Text command."""

from __future__ import annotations

import sys

import click

from ..transport import DangerousCommandError
from .context import TransportContext, pass_ctx


def register(cli: click.Group) -> None:
  """Register text command."""

  @cli.command("text", short_help="Send a text command.")
  @click.argument("command")
  @pass_ctx
  def text_cmd(tctx: TransportContext, command: str) -> None:
    """Send a text command.

    Example commands: dump_settings, force_touch_start.
    """
    transport = tctx.transport
    try:
      result = transport.send_text(command, allow_dangerous=tctx.force)
    except DangerousCommandError as error:
      click.echo(f"Error: {error}", err=True)
      sys.exit(1)
    if result:
      click.echo(result.strip())
    else:
      click.echo("No response")
