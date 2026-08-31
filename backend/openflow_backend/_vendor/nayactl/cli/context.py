## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Shared CLI transport context."""

from __future__ import annotations

import click

from ..constants import SIDE_DEST
from ..transport import SerialTransport, Transport, auto_connect
from ..types import DeviceInfo


class TransportContext:
  """Lazy transport initialization from CLI options."""

  def __init__(self) -> None:
    self.port: str | None = None
    self.side: str | None = None
    self.force: bool = False
    self.verbose: bool = False
    self._transport: Transport | None = None

  @property
  def transport(self) -> Transport:
    """Get a transport for the targeted side (or first available)."""
    if self._transport is None:
      self._transport = auto_connect(
        port=self.port,
        side=self.side or "left",
      )
    return self._transport

  def connect_to(self, device: DeviceInfo) -> Transport:
    """Open a transport to a specific discovered device."""
    dest = SIDE_DEST.get(device.side, 0x50)
    transport = SerialTransport(device.port, dest)
    transport.connect()
    return transport

  def close(self) -> None:
    if self._transport is not None:
      self._transport.disconnect()


pass_ctx = click.make_pass_decorator(TransportContext, ensure=True)
