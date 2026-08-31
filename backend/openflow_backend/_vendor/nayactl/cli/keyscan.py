## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Keyscan command."""

from __future__ import annotations

import signal
import sys
import time

import click

from ..constants import CAT_SYSTEM, SYS_TOGGLE_KEYSCAN_MODE
from ..protocol import parse_response
from ..util import format_subcmd, hexline
from .context import TransportContext, pass_ctx


def register(cli: click.Group) -> None:
  """Register keyscan command."""

  @cli.command()
  @click.option("--duration", "-d", type=int, default=30, help="Listen duration in seconds (default: 30)")
  @pass_ctx
  def keyscan(tctx: TransportContext, duration: int) -> None:
    """Enable keyscan mode and stream key events."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    enabled = False

    def cleanup(sig=None, frame=None) -> None:
      nonlocal enabled
      if enabled:
        click.echo("\nDisabling keyscan mode...")
        try:
          transport.send_command(dest, CAT_SYSTEM, SYS_TOGGLE_KEYSCAN_MODE, bytes([0x00]))
        except Exception:
          pass
        enabled = False
      if sig is not None:
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    responses = transport.send_command(dest, CAT_SYSTEM, SYS_TOGGLE_KEYSCAN_MODE, bytes([0x01]))
    if responses and any(response.valid for response in responses):
      enabled = True
      click.echo(f"Keyscan enabled. Listening {duration}s... (Ctrl+C to stop)")
    else:
      click.echo("Failed to enable keyscan mode.")
      return

    try:
      event_count = 0
      start = time.time()

      def on_frame(frame: bytes) -> None:
        nonlocal event_count
        response = parse_response(frame)
        elapsed = time.time() - start
        if response.valid and response.subcmd == 0x1009 and len(response.payload) >= 3:
          state = "PRESS" if response.payload[2] == 0 else "RELEASE"
          click.echo(f"  [{elapsed:7.3f}s] row={response.payload[0]} col={response.payload[1]} {state}")
          event_count += 1
        elif response.valid:
          click.echo(
            f"  [{elapsed:7.3f}s] {format_subcmd(response.category, response.subcmd)}: "
            f"{hexline(response.payload)}",
          )
          event_count += 1
        else:
          click.echo(f"  [{elapsed:7.3f}s] raw: {hexline(frame[:40])}")

      transport.listen(duration, on_frame)
      click.echo(f"\n{event_count} events in {duration}s.")
    finally:
      cleanup()
