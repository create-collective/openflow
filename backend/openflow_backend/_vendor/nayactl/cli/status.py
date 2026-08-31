## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Status command."""

from __future__ import annotations

import click

from ..constants import (
  BLE_GET_ADDRESS,
  CAT_BLE,
  CAT_MODULE,
  CAT_SYSTEM,
  MOD_DETECT,
  MOD_GET_BATTERY,
  MOD_GET_FW_VERSION,
  MOD_GET_PRECISE_BATTERY,
  MOD_SEND_HANDSHAKE,
  MODULE_TYPES,
  SYS_GET_FW_VERSION,
  SYS_GET_HW_ID_NUMBER,
  SYS_GET_KB_BATTERY_LEVEL,
)
from ..discovery import find_naya_serial_ports
from ..transport import Transport, TransportError
from ..util import format_fw_version, hexline
from .context import TransportContext, pass_ctx
from .responses import first_payload


def _query_half(transport: Transport, dest: int, verbose: bool = False) -> dict:
  """Query a single keyboard half for its status and module info."""
  info: dict = {}

  payload = first_payload(transport.send_command(dest, CAT_SYSTEM, SYS_GET_FW_VERSION))
  if payload is not None:
    info["fw_version"] = format_fw_version(payload)
    if verbose:
      click.echo(f"  [raw] GET_FW_VERSION: {hexline(payload)}")

  payload = first_payload(transport.send_command(dest, CAT_SYSTEM, SYS_GET_HW_ID_NUMBER))
  if payload is not None:
    try:
      info["hw_id"] = payload.decode("ascii")
    except (UnicodeDecodeError, ValueError):
      info["hw_id"] = hexline(payload)

  kb_voltages = []
  for _ in range(5):
    payload = first_payload(
      transport.send_command(dest, CAT_SYSTEM, SYS_GET_KB_BATTERY_LEVEL, timeout=0.5),
    )
    if payload is not None and len(payload) >= 2:
      kb_voltages.append((payload[0] << 8) | payload[1])

  if kb_voltages:
    kb_voltages.sort()
    millivolts = kb_voltages[len(kb_voltages) // 2]
    clamped = max(3300, min(4200, millivolts))
    info["battery"] = max(1, min(100, ((clamped - 3300) * 100) // 900))
    info["kb_voltage"] = millivolts
    if verbose:
      click.echo(
        f"  [raw] GET_KB_BATTERY_LEVEL: voltages={kb_voltages} "
        f"median={millivolts} mV → {info['battery']}%",
      )

  payload = first_payload(transport.send_command(dest, CAT_BLE, BLE_GET_ADDRESS))
  if payload is not None and len(payload) >= 6:
    info["ble_addr"] = ":".join(f"{b:02X}" for b in payload[:6])
    if verbose:
      click.echo(f"  [raw] BLE_GET_ADDRESS: {hexline(payload)}")

  transport.send_command(dest, CAT_MODULE, MOD_SEND_HANDSHAKE, timeout=1.5)
  payload = first_payload(transport.send_command(dest, CAT_MODULE, MOD_DETECT))
  if verbose and payload is not None:
    click.echo(f"  [raw] MODULE_DETECT: {hexline(payload)}")

  if payload is not None and len(payload) >= 1 and payload[0] != 0:
    module_info: dict = {}
    module_info["type"] = MODULE_TYPES.get(payload[0], f"Unknown ({payload[0]})")

    module_payload = first_payload(transport.send_command(dest, CAT_MODULE, MOD_GET_FW_VERSION))
    if module_payload is not None:
      module_info["fw_version"] = format_fw_version(module_payload)
      if verbose:
        click.echo(f"  [raw] MODULE_FW_VERSION: {hexline(module_payload)}")

    module_payload = first_payload(transport.send_command(dest, CAT_MODULE, MOD_GET_PRECISE_BATTERY))
    if module_payload is not None and len(module_payload) >= 2:
      if verbose:
        click.echo(f"  [raw] MODULE_PRECISE_BATTERY: {hexline(module_payload)}")
      voltage = (module_payload[0] << 8) | module_payload[1]
      valid = (module_payload[2] == 0) if len(module_payload) >= 3 else True
      if valid and voltage > 0:
        module_info["voltage"] = voltage
        clamped = max(33000, min(42000, voltage))
        module_info["battery"] = max(1, min(100, ((clamped - 33000) * 100) // 9000))

    if "battery" not in module_info:
      batt_voltages = []
      usb_voltages = []
      for _ in range(5):
        module_payload = first_payload(
          transport.send_command(dest, CAT_MODULE, MOD_GET_BATTERY, timeout=0.5),
        )
        if module_payload is not None and len(module_payload) >= 3:
          batt_voltages.append((module_payload[1] << 8) | module_payload[2])
          if len(module_payload) >= 5:
            usb_voltages.append((module_payload[3] << 8) | module_payload[4])
      if batt_voltages:
        batt_voltages.sort()
        raw_voltage = batt_voltages[len(batt_voltages) // 2]
        if raw_voltage > 0:
          clamped = max(33000, min(42000, raw_voltage))
          module_info["battery"] = max(1, min(100, ((clamped - 33000) * 100) // 9000))
          module_info["voltage"] = raw_voltage
        if verbose:
          click.echo(
            f"  [raw] MODULE_GET_BATTERY: voltages={batt_voltages} "
            f"median={raw_voltage}",
          )
      if usb_voltages:
        usb_voltages.sort()
        usb_voltage = usb_voltages[len(usb_voltages) // 2]
        if usb_voltage > 0:
          module_info["usb_voltage"] = usb_voltage
          if usb_voltage > 4000:
            module_info["charging_source"] = "Qi" if usb_voltage < 45000 else "USB"

    info["module"] = module_info

  return info


def _print_half_status(label: str, info: dict) -> None:
  """Pretty-print the status of one keyboard half."""
  click.echo(f"{label}:")
  if "fw_version" in info:
    click.echo(f"  Firmware:    {info['fw_version']}")
  if "hw_id" in info:
    click.echo(f"  HW ID:       {info['hw_id']}")
  if "ble_addr" in info:
    click.echo(f"  BLE Address: {info['ble_addr']}")
  if "battery" in info:
    click.echo(f"  Battery:     {info['battery']}%")
  if "kb_voltage" in info:
    millivolts = info["kb_voltage"]
    click.echo(f"  Voltage:     {millivolts / 1000:.3f}V")

  module_info = info.get("module")
  if module_info:
    click.echo(f"  Module:      {module_info.get('type', 'Unknown')}")
    if "fw_version" in module_info:
      click.echo(f"    Firmware:  {module_info['fw_version']}")
    if "battery" in module_info:
      click.echo(f"    Battery:   {module_info['battery']}%")
    if "voltage" in module_info:
      voltage = module_info["voltage"]
      click.echo(f"    Voltage:   {voltage / 10000:.4f}V")
    if "usb_voltage" in module_info:
      usb_voltage = module_info["usb_voltage"]
      click.echo(f"    USB/Qi:    {usb_voltage / 10000:.4f}V")
    if "charging_source" in module_info:
      click.echo(f"    Charging:  {module_info['charging_source']}")
    if "battery" not in module_info:
      click.echo("    Battery:   unknown")
  else:
    click.echo("  Module:      None")


def register(cli: click.Group) -> None:
  """Register status command."""

  @cli.command()
  @pass_ctx
  def status(tctx: TransportContext) -> None:
    """Show device status for all connected halves and modules."""
    if tctx.port:
      transport = tctx.transport
      dest = getattr(transport, "dest", 0x50)
      info = _query_half(transport, dest, verbose=tctx.verbose)
      _print_half_status(tctx.side or "device", info)
      return

    devices = find_naya_serial_ports()
    if not devices:
      click.echo("No Naya Create devices found.")
      return

    if tctx.side:
      devices = [device for device in devices if device.side == tctx.side]
      if not devices:
        click.echo(f"No {tctx.side} half found.")
        return

    for index, device in enumerate(devices):
      if index > 0:
        click.echo()
      try:
        transport = tctx.connect_to(device)
        dest = getattr(transport, "dest", 0x50)
        info = _query_half(transport, dest, verbose=tctx.verbose)
        _print_half_status(device.description, info)
        transport.disconnect()
      except TransportError as error:
        click.echo(f"{device.description} ({device.port}): {error}")
