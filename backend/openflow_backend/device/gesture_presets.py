"""Preset actions offered per module gesture, for the OpenFlow gesture dropdowns.

Each editable gesture shows a curated preset list (common, sensible actions) plus a "Custom…"
choice the frontend fulfils with the normal key/action picker (any keycode, like the Backspace
1-finger tap). Presets are action_code strings that the encoder already handles (`encode_keypress`).
"""
from __future__ import annotations

from . import module_fields as mf

# Curated presets by module family. All are HID keys/consumer codes the encoder can emit.
_MEDIA = [
    ("C_PLAY_PAUSE", "Play / Pause"), ("C_MUTE", "Mute"),
    ("C_VOL_UP", "Volume Up"), ("C_VOL_DOWN", "Volume Down"),
    ("C_NEXT", "Next Track"), ("C_PREVIOUS", "Previous Track"),
    ("C_FAST_FORWARD", "Fast Forward"), ("C_REWIND", "Rewind"),
    ("C_STOP", "Stop"),
    ("C_BRIGHTNESS_INC", "Brightness Up"), ("C_BRIGHTNESS_DEC", "Brightness Down"),
]
_NAV = [
    ("HOME", "Home"), ("END", "End"), ("PG_UP", "Page Up"), ("PG_DN", "Page Down"),
    ("UP", "Up"), ("DOWN", "Down"), ("LEFT", "Left"), ("RIGHT", "Right"),
    ("ESC", "Escape"), ("RETURN", "Enter"), ("TAB", "Tab"), ("BACKSPACE", "Backspace"),
]

PRESETS: dict[str, list[tuple[str, str]]] = {
    "TUNE": _MEDIA,
    "TRACK": _NAV + _MEDIA,
    "TOUCH": _NAV + _MEDIA,
    "FLOAT": _MEDIA,
}


def presets_for(module_type: str) -> list[dict]:
    return [{"action_type": "key", "action_code": c, "label": lbl}
            for c, lbl in PRESETS.get(module_type.upper(), [])]


def gestures_for(module_type: str) -> list[dict]:
    """The editable gestures of a module, each with its default action + preset options.

    Shape the dropdown UI consumes: {gesture, field, default_action, presets, allow_custom}.
    `default_action` is the stock action from the recovered default map (the current on-device
    binding overlays this once a live read is available)."""
    fm = mf.field_map(module_type)
    presets = presets_for(module_type)
    out = []
    for field_hex, info in fm.items():
        if info.get("kind") != "keypress" or not info.get("gesture"):
            continue
        out.append({
            "gesture": info["gesture"],
            "field": int(field_hex, 16),
            "default_action": info.get("default_action"),
            "presets": presets,
            "allow_custom": True,
        })
    out.sort(key=lambda g: g["field"])
    return out
