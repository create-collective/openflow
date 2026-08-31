## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""BLE command group."""

from __future__ import annotations

import click

from ..constants import BLE_GET_ADDRESS, BLE_GET_ALL_PAIRS, BLE_GET_STATUS, CAT_BLE
from ..util import hexline
from .context import TransportContext, pass_ctx
from .responses import first_payload


def register(cli: click.Group) -> None:
  """Register BLE command group."""

  @click.group()
  def ble() -> None:
    """Bluetooth commands."""

  @ble.command("address")
  @pass_ctx
  def ble_address(tctx: TransportContext) -> None:
    """Get BLE MAC address."""
    from ..bluetooth import _mac

    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    payload = first_payload(transport.send_command(dest, CAT_BLE, BLE_GET_ADDRESS))
    if payload is not None and len(payload) >= 6:
      click.echo(f"  BLE address: {_mac(payload)}")
    else:
      click.echo("  No response")

  @ble.command("status")
  @pass_ctx
  def ble_status(tctx: TransportContext) -> None:
    """Get full BLE status (CreateLeft only)."""
    from ..bluetooth import parse_ble_status

    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    payload = first_payload(transport.send_command(dest, CAT_BLE, BLE_GET_STATUS, timeout=2.0))
    if payload is None:
      click.echo("  No response")
      return
    if tctx.verbose:
      click.echo(f"  [raw] BLE_GET_STATUS ({len(payload)} bytes): {hexline(payload[:32])}...")
    status = parse_ble_status(payload)
    if status is None:
      click.echo(f"  Invalid response (got {len(payload)} bytes, expected ≥239)")
      return
    click.echo(f"  Revision:        {status.revision}")
    click.echo(f"  Local address:   {status.local_address} (type {status.local_address_type})")
    click.echo(f"  Address valid:   {status.local_addr_valid}")
    click.echo(f"  Advertising:     {status.advertising_status}")
    click.echo(f"  Host connected:  {status.host_connected}")
    click.echo(f"  Conn mode:       {status.global_conn_mode}")
    click.echo(f"  Profile count:   {status.profile_count}")
    click.echo(f"  Active profile:  {status.active_profile}")
    click.echo()
    for profile in status.profiles:
      if not profile.configured and not profile.has_peer_addr:
        continue
      marker = " (active)" if profile.profile_index == status.active_profile else ""
      click.echo(f"  Profile {profile.profile_index}{marker}:")
      click.echo(f"    Peer:        {profile.peer_address}")
      click.echo(f"    Configured:  {profile.configured}")
      click.echo(f"    Bonded:      {profile.bonded}")
      click.echo(f"    Connected:   {profile.connected}")
      click.echo(f"    Encrypted:   {profile.encrypted}")
      click.echo(f"    Auth:        {profile.authenticated}")
      if profile.connected:
        click.echo(f"    Interval:    {profile.connection_interval}")
        click.echo(f"    Latency:     {profile.connection_latency}")
        click.echo(f"    Timeout:     {profile.connection_timeout}")
        click.echo(f"    PHY tx/rx:   {profile.phy_tx}/{profile.phy_rx}")
    if status.last_disconnect_reason or status.packet_error_count:
      click.echo(f"  Last disconnect reason: {status.last_disconnect_reason}")
      click.echo(f"  Packet error count:     {status.packet_error_count}")

  @ble.command("pairs")
  @pass_ctx
  def ble_pairs(tctx: TransportContext) -> None:
    """List BLE paired device MAC addresses."""
    from ..bluetooth import parse_ble_pairs

    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    payload = first_payload(transport.send_command(dest, CAT_BLE, BLE_GET_ALL_PAIRS))
    if payload is None:
      click.echo("  No response")
      return
    if tctx.verbose:
      click.echo(f"  [raw] BLE_GET_ALL_PAIRS: {hexline(payload)}")
    pairs = parse_ble_pairs(payload)
    if not pairs:
      click.echo("  No paired devices")
      return
    click.echo(f"  Paired devices ({len(pairs)}):")
    for index, mac in enumerate(pairs):
      click.echo(f"    {index}: {mac}")

  cli.add_command(ble)
