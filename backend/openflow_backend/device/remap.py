"""REMAP protocol (category 0x30) — layers, macros, module configs, LED maps.

PHASE 2 SCAFFOLD. The opcodes below are documented (nayactl docs/cdc-protocol.md)
but the payload wire format is NOT yet reverse-engineered, so nothing here talks
to hardware until the encoders/decoders are filled in. This module is deliberately
kept clean and hardware-agnostic so it can be contributed upstream to nayactl.

Reverse-engineering leads (from D:\\NayaOS\\docs\\nayacore-source-map.txt):
  - constructRemapCommands.cpp   -> how WRITE_* payloads are built
  - interpretRemapData.cpp       -> how READ_* payloads are parsed
  - Naya_Layer.cpp / Naya_Binding.cpp -> the layer/binding struct layout
Keycode vocabulary + ZMK behaviour mapping: D:\\NayaOS\\docs\\device-constants.txt
DB shape these map onto: openflow_backend/db/schema.sql (layers/keys/key_bindings/
macros/module_configs).

Workflow once hardware is available:
  1. `dump_settings` + READ LAYER LIST/DATA on a known keymap
  2. diff against a single remapped key to locate the binding struct
  3. implement decode_* first (read-only, safe), validate against the DB shape
  4. implement encode_* + round-trip write/re-read to confirm
"""

from __future__ import annotations

from dataclasses import dataclass

from .._vendor.nayactl.constants import CAT_REMAP  # noqa: F401  (category byte)

# --- Opcodes (subcmd IDs within category 0x30) ---
READ_LAYER_LIST = 0x1001
WRITE_LAYER_LIST = 0x1002
READ_LAYER_DATA = 0x1003
WRITE_LAYER_DATA = 0x1004
READ_MACRO_LIST = 0x1005
WRITE_MACRO_LIST = 0x1006
READ_MACRO_DATA = 0x1007
WRITE_MACRO_DATA = 0x1008
READ_MODULE_CONFIG_LIST = 0x1009
WRITE_MODULE_CONFIG_LIST = 0x100A
READ_MODULE_CONFIG_DATA = 0x100B
WRITE_MODULE_CONFIG_DATA = 0x100C
READ_LED_MAP_DATA = 0x100D
WRITE_LED_MAP_DATA = 0x100E
CLEAR_ALL_DATA = 0x10CA


@dataclass
class LayerBinding:
    """One key binding within a layer (maps to the key_bindings table)."""

    position_id: int
    behavior: str           # tap / hold / double_tap / tap+hold / double_tap+hold
    action_type: str
    action_code: str
    context: str | None = None


class RemapNotImplemented(NotImplementedError):
    """Raised by every codec until Phase 2 reverse-engineering is done."""


def decode_layer_list(payload: bytes) -> list[dict]:
    raise RemapNotImplemented("READ LAYER LIST payload format not yet reversed")


def decode_layer_data(payload: bytes) -> list[LayerBinding]:
    raise RemapNotImplemented("READ LAYER DATA payload format not yet reversed")


def encode_layer_data(bindings: list[LayerBinding]) -> bytes:
    raise RemapNotImplemented("WRITE LAYER DATA payload format not yet reversed")
