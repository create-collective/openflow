## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Raw command."""

from __future__ import annotations

import sys

import click

from ..transport import DangerousCommandError
from ..util import format_category, format_subcmd, hexline
from .context import TransportContext, pass_ctx


def register(cli: click.Group) -> None:
  """Register raw command."""

  @cli.command("raw")
  @click.argument("category", type=str)
  @click.argument("subcmd", type=str)
  @click.argument("payload", type=str, default="")
  @pass_ctx
  def raw_cmd(tctx: TransportContext, category: str, subcmd: str, payload: str) -> None:
    """Send a raw binary CDC command.

    CATEGORY and SUBCMD are hex values (e.g. 0xFE 0x1004).
    PAYLOAD is optional hex bytes (e.g. 01 or 0102ff).
    """
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)

    cat = int(category, 0)
    sub = int(subcmd, 0)
    pay = bytes.fromhex(payload.replace(" ", "").replace("0x", "")) if payload else b""

    try:
      responses = transport.send_command(dest, cat, sub, pay, allow_dangerous=tctx.force)
    except DangerousCommandError as error:
      click.echo(f"Error: {error}", err=True)
      sys.exit(1)

    if not responses:
      click.echo("No response")
      return

    for index, response in enumerate(responses):
      if response.valid:
        click.echo(
          f"  Response #{index + 1}: "
          f"cat={format_category(response.category)} "
          f"subcmd={format_subcmd(response.category, response.subcmd)} "
          f"payload={hexline(response.payload)} "
          f"checksum={'OK' if response.checksum_ok else 'FAIL'}",
        )
      else:
        click.echo(f"  Response #{index + 1} (raw): {hexline(response.raw[:60])}")
