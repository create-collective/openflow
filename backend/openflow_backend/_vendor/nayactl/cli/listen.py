## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Listen command."""

from __future__ import annotations

import time

import click

from ..protocol import parse_response
from ..util import format_category, format_subcmd, hexline
from .context import TransportContext, pass_ctx


def register(cli: click.Group) -> None:
  """Register listen command."""

  @cli.command()
  @click.option("--duration", "-d", type=int, default=60, help="Listen duration in seconds (default: 60)")
  @pass_ctx
  def listen(tctx: TransportContext, duration: int) -> None:
    """Passively listen for all incoming CDC data."""
    transport = tctx.transport
    click.echo(f"Listening for {duration}s... (Ctrl+C to stop)")

    event_count = 0
    start = time.time()

    def on_frame(frame: bytes) -> None:
      nonlocal event_count
      elapsed = time.time() - start
      event_count += 1
      response = parse_response(frame)
      if response.valid:
        click.echo(
          f"  [{elapsed:7.3f}s] "
          f"{format_category(response.category)} "
          f"{format_subcmd(response.category, response.subcmd)} "
          f"payload={hexline(response.payload)}",
        )
      else:
        click.echo(f"  [{elapsed:7.3f}s] raw ({len(frame)}b): {hexline(frame[:48])}")
        try:
          text = frame.decode("ascii", errors="strict")
          click.echo(f"           text: {text.strip()}")
        except (UnicodeDecodeError, ValueError):
          pass

    try:
      transport.listen(duration, on_frame)
    except KeyboardInterrupt:
      pass
    click.echo(f"\n{event_count} frames in {time.time() - start:.1f}s.")
