## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""nayactl CLI package."""

from __future__ import annotations

import click

from .. import __version__
from .ble import register as register_ble
from .context import TransportContext
from .keyscan import register as register_keyscan
from .led import register as register_led
from .listen import register as register_listen
from .module import register as register_module
from .raw import register as register_raw
from .scan import register as register_scan
from .status import register as register_status
from .text import register as register_text


@click.group()
@click.option("--port", "-p", default=None, help="Serial port (auto-detected if omitted)")
@click.option(
  "--side",
  type=click.Choice(["left", "right", "dongle"]),
  default=None,
  help="Target a specific keyboard half (default: all)",
)
@click.option("--force", is_flag=True, help="Allow dangerous commands")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.version_option(__version__, prog_name="nayactl")
@click.pass_context
def cli(ctx: click.Context, port: str | None, side: str | None, force: bool, verbose: bool) -> None:
  """CLI tool for the Naya Create split keyboard."""
  tctx = TransportContext()
  tctx.port = port
  tctx.side = side
  tctx.force = force
  tctx.verbose = verbose
  ctx.obj = tctx
  ctx.call_on_close(tctx.close)


register_scan(cli)
register_status(cli)
register_module(cli)
register_ble(cli)
register_led(cli)
register_keyscan(cli)
register_text(cli)
register_raw(cli)
register_listen(cli)
