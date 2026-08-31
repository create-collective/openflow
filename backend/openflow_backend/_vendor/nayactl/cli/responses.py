## @file
# Copyright (c) 2026, Cory Bennett. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
##
"""Helpers for handling command responses."""

from __future__ import annotations


def first_payload(responses: list) -> bytes | None:
  """Return the payload from the first valid response, or None."""
  for response in responses:
    if response.valid:
      return response.payload
  return None
