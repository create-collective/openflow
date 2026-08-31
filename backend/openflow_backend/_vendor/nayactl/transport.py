## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Transport layer: serial and ZMQ backends."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Callable

import serial

from .constants import (
  BAUD_RATE, CAT_SYSTEM, DANGEROUS_COMMANDS, DANGEROUS_TEXT_COMMANDS,
  DEST_LEFT, EOT, SIDE_DEST, SYS_GET_FW_VERSION, SYS_MEDIA_ID_REQUEST,
)
from .protocol import build_message, build_text_command, parse_response
from .types import CDCResponse


class TransportError(Exception):
  pass


class DangerousCommandError(TransportError):
  pass


class Transport(ABC):
  """Abstract transport for communicating with a Naya keyboard."""

  @abstractmethod
  def connect(self) -> None: ...

  @abstractmethod
  def disconnect(self) -> None: ...

  @abstractmethod
  def send_command(
    self,
    dest: int,
    category: int,
    subcmd: int,
    payload: bytes = b"",
    timeout: float = 2.5,
  ) -> list[CDCResponse]: ...

  @abstractmethod
  def send_text(self, command: str, timeout: float = 3.0) -> str: ...

  @abstractmethod
  def listen(self, duration: float, callback: Callable[[bytes], None]) -> None: ...

  @property
  @abstractmethod
  def is_connected(self) -> bool: ...


class SerialTransport(Transport):
  """Direct CDC serial communication with the keyboard."""

  def __init__(self, port: str, dest: int = DEST_LEFT):
    self.port = port
    self.dest = dest
    self._ser: serial.Serial | None = None
    self._handshake_done = False

  def connect(self) -> None:
    try:
      self._ser = serial.Serial(
        port=self.port,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.1,
        dsrdtr=True,
      )
    except serial.SerialException as e:
      raise TransportError(f"Cannot open {self.port}: {e}") from e
    self._ser.dtr = True
    self._ser.rts = True
    self._drain()
    self._handshake()

  def disconnect(self) -> None:
    if self._ser and self._ser.is_open:
      self._ser.close()
    self._ser = None
    self._handshake_done = False

  @property
  def is_connected(self) -> bool:
    return self._ser is not None and self._ser.is_open and self._handshake_done

  def send_command(
    self,
    dest: int,
    category: int,
    subcmd: int,
    payload: bytes = b"",
    timeout: float = 1.0,
    allow_dangerous: bool = False,
  ) -> list[CDCResponse]:
    key = (category, subcmd)
    if key in DANGEROUS_COMMANDS and not allow_dangerous:
      name = DANGEROUS_COMMANDS[key]
      raise DangerousCommandError(
        f"{name} is a dangerous command. Use --force to execute."
      )
    msg = build_message(dest, category, subcmd, payload)
    return self._send_raw(msg, timeout)

  def send_text(
    self,
    command: str,
    timeout: float = 3.0,
    allow_dangerous: bool = False,
  ) -> str:
    cmd_name = command.strip().split("#")[0]  # strip parameters
    if cmd_name in DANGEROUS_TEXT_COMMANDS and not allow_dangerous:
      raise DangerousCommandError(
        f"'{cmd_name}' is a dangerous command. Use --force to execute."
      )
    self._assert_open()
    self._ser.reset_input_buffer()
    self._ser.write(build_text_command(command))
    self._ser.flush()
    # Read eagerly — return as soon as we get a complete response
    buf = bytearray()
    start = time.time()
    while time.time() - start < timeout:
      chunk = self._ser.read(256)
      if chunk:
        buf.extend(chunk)
        # Text responses end with \r\n — if we have one, we're done
        if b"\r\n" in buf or b"\n" in buf:
          break
      elif buf:
        break  # got data, no more coming
    if buf:
      try:
        return buf.decode("ascii", errors="replace")
      except Exception:
        return buf.hex()
    return ""

  def listen(self, duration: float, callback: Callable[[bytes], None]) -> None:
    self._assert_open()
    self._ser.reset_input_buffer()
    buf = bytearray()
    frames: list[bytes] = []
    start = time.time()
    while time.time() - start < duration:
      chunk = self._ser.read(256)
      if chunk:
        buf.extend(chunk)
        frames.clear()
        buf = self._extract_frames(buf, frames)
        for frame in frames:
          callback(frame)

  def send_raw(self, data: bytes, timeout: float = 2.5) -> list[CDCResponse]:
    """Send pre-built raw bytes and collect responses."""
    return self._send_raw(data, timeout)

  # --- Internal ---

  def _assert_open(self) -> None:
    if not self._ser or not self._ser.is_open:
      raise TransportError("Serial port not open")

  def _drain(self) -> None:
    if self._ser:
      self._ser.reset_input_buffer()
      time.sleep(0.1)
      self._ser.read(4096)

  def _handshake(self) -> None:
    """CDC handshake: MEDIA_ID_REQUEST then GET_FW_VERSION.

    The keyboard needs the MEDIA_ID_REQUEST to activate the CDC protocol
    channel. On first connect this may take up to ~1s to wake up, but
    subsequent commands are fast.
    """
    self._drain()
    msg1 = build_message(self.dest, CAT_SYSTEM, SYS_MEDIA_ID_REQUEST)
    msg2 = build_message(self.dest, CAT_SYSTEM, SYS_GET_FW_VERSION)

    # Try with increasing delays — first connect needs more time
    for wait in (0.3, 0.7, 1.0):
      self._write_and_wait(msg1, wait)
      responses = self._send_raw(msg2, timeout=0.5)
      if responses and any(r.valid for r in responses):
        self._handshake_done = True
        return

    raise TransportError(
      "Keyboard did not respond to handshake. "
      "Is it connected and powered on?"
    )

  def _write_and_wait(self, data: bytes, wait: float) -> bytes:
    self._assert_open()
    self._ser.reset_input_buffer()
    self._ser.write(data)
    self._ser.flush()
    time.sleep(wait)
    return self._ser.read(4096)

  def _send_raw(self, data: bytes, timeout: float) -> list[CDCResponse]:
    self._assert_open()
    self._ser.reset_input_buffer()
    self._ser.write(data)
    self._ser.flush()
    frames = self._read_frames(timeout)
    return [parse_response(f) for f in frames]

  def _read_frames(self, timeout: float) -> list[bytes]:
    """Read all CDC frames within timeout, using data_size for boundaries.

    Frame structure:
          [0xAA, src, dst, 0x00, category, data_size, ...data_region..., checksum, 0x04]
          Total length = 6 + data_size + 2
    """
    frames: list[bytes] = []
    buf = bytearray()
    start = time.time()
    while time.time() - start < timeout:
      chunk = self._ser.read(256)
      if chunk:
        buf.extend(chunk)
        buf = self._extract_frames(buf, frames)
      elif frames:
        break
    return frames

  @staticmethod
  def _extract_frames(buf: bytearray, frames: list[bytes]) -> bytearray:
    """Extract complete CDC frames from buffer using data_size field."""
    while len(buf) >= 6:
      # Look for frame start (0xAA header byte)
      try:
        start = buf.index(0xAA)
      except ValueError:
        buf.clear()
        break
      if start > 0:
        buf = buf[start:]
      if len(buf) < 6:
        break
      data_size = buf[5]
      frame_len = 6 + data_size + 2  # header(6) + data + checksum(1) + EOT(1)
      if len(buf) < frame_len:
        break  # wait for more data
      frame = bytes(buf[:frame_len])
      buf = buf[frame_len:]
      # Validate EOT at expected position
      if frame[-1] == EOT:
        frames.append(frame)
      # else: corrupted frame, skip it
    return buf


def auto_connect(
  port: str | None = None,
  side: str = "left",
  prefer_zmq: bool = True,
) -> Transport:
  """Auto-detect and connect to a Naya keyboard.

  If port is specified, connects directly via serial.
  Otherwise, discovers devices by VID/PID.
  ZMQ transport will be tried first when prefer_zmq=True.
  """
  from .discovery import find_naya_serial_port, find_naya_serial_ports

  dest = SIDE_DEST.get(side, DEST_LEFT)

  if port:
    transport = SerialTransport(port, dest)
    transport.connect()
    return transport

  # TODO: try ZMQ first if prefer_zmq

  device = find_naya_serial_port(side)
  if not device:
    devices = find_naya_serial_ports()
    if devices:
      device = devices[0]
    else:
      raise TransportError(
        "No Naya Create keyboard found. "
        "Is it connected via USB?"
      )

  transport = SerialTransport(device.port, dest)
  transport.connect()
  return transport
