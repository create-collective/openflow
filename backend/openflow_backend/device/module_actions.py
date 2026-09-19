"""The action vocabulary a MODULE gesture can be bound to.

Lives under device/ rather than db/ because the dependency runs one way: db imports device, never
the reverse, and api/rest.py imports both. Putting it in db/ and importing it from
actions_catalog would invert that and risk a cycle.

Still exported through db.userdata.get_modules() in its flat form, because AxisControls, the
"Imported" fallback row and setShortcutTableFromActions all consume the flat list.
"""
from __future__ import annotations

# Dropdown options for module gesture bindings. This holds every action our
# imported defaults use (so you can always reset to a default) plus the obvious
# extras, grouped for the <optgroup> UI. It's intentionally a working set — once
# firmware reverse-engineering shows what the modules can really do, revisit the
# codes/labels. `code` is stored in module_bindings.action_code; the UI shows
# `label`. Any imported value not listed here still renders as a synthetic option.
_CURSOR_V = "mouse - MOUSE_DOWN - MOUSE_UP"
_CURSOR_H = "mouse - MOUSE_LEFT - MOUSE_RIGHT"
MODULE_ACTIONS = [
    {"code": "", "label": "None", "actionType": "none", "group": ""},
    # Cursor / pointer (Touch 1-finger + Track vertical/horizontal)
    {"code": _CURSOR_V, "label": "Vertical Cursor Control", "actionType": "value", "group": "Cursor"},
    {"code": _CURSOR_H, "label": "Horizontal Cursor Control", "actionType": "value", "group": "Cursor"},
    # Scroll
    {"code": "mouse - SCROLL_UP - SCROLL_DOWN", "label": "Vertical Scroll", "actionType": "value", "group": "Scroll"},
    {"code": "mouse - SCROLL_LEFT - SCROLL_RIGHT", "label": "Horizontal Scroll", "actionType": "value", "group": "Scroll"},
    # Zoom binds to the 2-finger pinch axis on a Touch or Tune. NayaFlow has no zoom
    # action at all, which is why its own pinch & spread control could never be given one.
    {"code": "mouse - ZOOM_OUT - ZOOM_IN", "label": "Zoom", "actionType": "value", "group": "Scroll"},
    # Mouse buttons
    {"code": "M1", "label": "Left Click", "actionType": "mouse", "group": "Clicks"},
    {"code": "M2", "label": "Right Click", "actionType": "mouse", "group": "Clicks"},
    {"code": "M3", "label": "Middle Click", "actionType": "mouse", "group": "Clicks"},
    {"code": "M4", "label": "Mouse Button 4", "actionType": "mouse", "group": "Clicks"},
    # Media (Tune)
    {"code": "C_VOL_DOWN - C_VOL_UP", "label": "Volume", "actionType": "value", "group": "Media"},
    {"code": "C_PLAY_PAUSE", "label": "Play / Pause", "actionType": "key", "group": "Media"},
    {"code": "C_NEXT", "label": "Next Track", "actionType": "key", "group": "Media"},
    {"code": "C_PREVIOUS", "label": "Previous Track", "actionType": "key", "group": "Media"},
    {"code": "C_FAST_FORWARD", "label": "Fast Forward", "actionType": "key", "group": "Media"},
    {"code": "C_REWIND", "label": "Rewind", "actionType": "key", "group": "Media"},
    {"code": "C_MUTE", "label": "Mute", "actionType": "key", "group": "Media"},
    # Display & LED (Tune)
    {"code": "C_BRIGHTNESS_INC", "label": "Screen Brightness Up", "actionType": "key", "group": "Display & LED"},
    {"code": "C_BRIGHTNESS_DEC", "label": "Screen Brightness Down", "actionType": "key", "group": "Display & LED"},
    {"code": "LED_BRIGHTNESS_UP", "label": "Keyboard LED Brightness Up", "actionType": "LED", "group": "Display & LED"},
    {"code": "LED_BRIGHTNESS_DOWN", "label": "Keyboard LED Brightness Down", "actionType": "LED", "group": "Display & LED"},
    # Shortcuts (Touch swipe defaults)
    {"code": "LCTRL + TAB", "label": "Ctrl + Tab", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LCTRL + LSHIFT + TAB", "label": "Ctrl + Shift + Tab", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + ESC", "label": "Alt + Esc", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + LSHIFT + ESC", "label": "Alt + Shift + Esc", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LGUI + TAB", "label": "Win + Tab", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LGUI + LCTRL + LEFT", "label": "Win + Ctrl + Left", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LGUI + LCTRL + RIGHT", "label": "Win + Ctrl + Right", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + PG_UP", "label": "Alt + Page Up", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + PG_DN", "label": "Alt + Page Down", "actionType": "shortcut_alias", "group": "Shortcuts"},
]

# The shortcut dictionary, folded in. It carries the plain-English name, the chord, a glyph and
# the device bytes for each code -- so a dropdown can say "Next tab (Ctrl + Tab)" rather than
# "LCTRL + TAB", and a gesture row can be labelled by what it DOES.
#
# Nine of these were already listed above by hand; the dictionary entry wins on a clash, because
# its bytes are checked against a real flash capture. Grouped by purpose (Clipboard & text,
# Tabs & browser, Windows & desktops, ...) rather than dumped into one "Shortcuts" bucket, which
# at 82 entries would be unusable.
def _with_shortcut_dictionary(base: list) -> list:
    from ..device import shortcuts as _sc

    entries = _sc.as_module_actions()
    if not entries:
        return base                                   # dictionary missing: keep the hand list
    known = {e["code"] for e in entries}
    return [a for a in base if a["code"] not in known] + entries


MODULE_ACTIONS = _with_shortcut_dictionary(MODULE_ACTIONS)
