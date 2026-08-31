## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""LED command group."""

from __future__ import annotations

import click

from ..constants import CAT_LED, LED_ADJUST_BRIGHTNESS, LED_OFF, LED_ON, LED_SELECT_EFFECT
from .context import TransportContext, pass_ctx


def register(cli: click.Group) -> None:
  """Register LED command group."""

  @click.group()
  def led() -> None:
    """LED control commands."""

  @led.command("on")
  @pass_ctx
  def led_on(tctx: TransportContext) -> None:
    """Turn LEDs on."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    transport.send_command(dest, CAT_LED, LED_ON)
    click.echo("LEDs on")

  @led.command("off")
  @pass_ctx
  def led_off(tctx: TransportContext) -> None:
    """Turn LEDs off."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    transport.send_command(dest, CAT_LED, LED_OFF)
    click.echo("LEDs off")

  @led.command("brightness")
  @click.argument("level", type=int)
  @pass_ctx
  def led_brightness(tctx: TransportContext, level: int) -> None:
    """Set LED brightness (0-255)."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    transport.send_command(dest, CAT_LED, LED_ADJUST_BRIGHTNESS, bytes([level & 0xFF]))
    click.echo(f"Brightness set to {level}")

  @led.command("effect")
  @click.argument("effect_id", type=int)
  @pass_ctx
  def led_effect(tctx: TransportContext, effect_id: int) -> None:
    """Select LED effect by ID."""
    transport = tctx.transport
    dest = getattr(transport, "dest", 0x50)
    transport.send_command(dest, CAT_LED, LED_SELECT_EFFECT, bytes([effect_id & 0xFF]))
    click.echo(f"Effect set to {effect_id}")

  cli.add_command(led)
