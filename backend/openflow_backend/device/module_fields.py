"""Module-config field map: which device field index is which gesture, per module type.

Built by correlating a real device read (flash2.pcap slots 3/4) with the installer's default
bindings (docs/reference/naya-default-module-bindings.json). Powers the module gesture UI (label
each device field) and the gesture write path (map a gesture -> its keypress field for read-modify-
write). See docs/module-gestures.md.

Confidence: TUNE is confirmed from a real read. TRACK has only axis + speed fields on the device
(no on-device gesture keypress fields — its DB shortcut bindings were never flashed). TOUCH / FLOAT
have no device read yet, so no field map — read one when the module is connected.
"""
from __future__ import annotations

import json
from pathlib import Path

_MAP: dict = json.loads((Path(__file__).with_name("module_field_map.json")).read_text())


def field_map(module_type: str) -> dict:
    """{'0x0e': {kind, gesture, ...}, ...} for a module type ('TUNE'/'TRACK'/...)."""
    return _MAP.get(module_type.upper(), {}).get("fields", {})


def gesture_fields(module_type: str) -> dict[str, int]:
    """{gesture_string: field_index} for the keypress-writable gestures of this module."""
    return {v["gesture"]: int(k, 16)
            for k, v in field_map(module_type).items()
            if v.get("kind") == "keypress" and v.get("gesture")}


# Action types that encode as a device keypress (what a keypress gesture field accepts).
KEYPRESS_ACTION_TYPES = {"key", "modifier", "shortcut_alias"}


def gesture_kind(module_type: str, behavior: str) -> str | None:
    """The device field kind for a gesture behavior string ('keypress'/'axis'/...), or None
    if that gesture has no field on the device (unknown module, or not stored on-device)."""
    for v in field_map(module_type).values():
        if v.get("gesture") == behavior:
            return v.get("kind")
    return None


def action_ok_for_kind(action_type: str, field_kind: str | None) -> bool:
    """Whether an action_type can be flashed into a field of this kind. Used to filter the
    gesture dropdown so the UI never offers something the firmware could not accept."""
    if action_type == "none":
        return True
    if field_kind == "keypress":
        return action_type in KEYPRESS_ACTION_TYPES
    if field_kind == "axis":
        return action_type == "value"
    return False  # unknown field kind, or LED/mouse — not confirmed writable


def label_fields(module_type: str, parsed_fields: list[tuple[int, int, bytes]]) -> list[dict]:
    """Annotate a device read (list of (field, type, value)) with gesture labels for the UI.

    Returns [{field, kind, gesture, editable, value}] — `editable` marks the keypress gesture
    fields a user can rebind (custom key or a preset)."""
    fm = field_map(module_type)
    out = []
    for field, typ, val in parsed_fields:
        info = fm.get(f"0x{field:02x}", {})
        out.append({
            "field": field,
            "type": typ,
            "kind": info.get("kind", "unknown"),
            "gesture": info.get("gesture"),
            "editable": info.get("kind") == "keypress" and bool(info.get("gesture")),
            "value": val.hex(),
        })
    return out
