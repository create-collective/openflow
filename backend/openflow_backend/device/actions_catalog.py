"""The action palette — what a user can bind to a key.

Organized into the tabs NayaFlow uses:
  - "B" (basic):    Letters, Numbers, Modifiers, Symbols
  - "+" (extended): Empty (Transparent/Disable), Mouse, Connection, Recovery,
                    System, Keypad, Navigation, International, Locks, Function
  - "✦" (layers):   Hold / Toggle / Force / Sticky layer (bound to a target layer)
  - "↗" (shortcuts):MacOS / Windows / VS Code presets

Action *codes* are functional facts (must match firmware/DB); labels are OpenFlow's
own (clean reskin). `actionType` matches NayaFlow's key_bindings.action_type so data
round-trips. Some actions are marked comingSoon (present for parity, not yet wired).
"""

from __future__ import annotations

# action_type -> ZMK behaviour (reference; device-constants.txt 226-233)
ZMK_BEHAVIOUR = {
    "KEY_PRESS": "&kp", "MOD_TAP": "&mt", "TO_LAYER": "&to", "TOGGLE_LAYER": "&tog",
    "STICKY_LAYER": "&sl", "MO": "&mo", "RGB_UG": "&rgb_ug", "BLUETOOTH": "&bt",
    "OUTPUTS": "&out",
}

# Layer-switch action types (frontendType) -> action_code prefix + label.
LAYER_ACTION_TYPES = {
    "layer_polite_hold": {"prefix": "MO_LAYER_", "label": "Hold Layer"},
    "layer_polite_toggle": {"prefix": "TOGGLE_LAYER_", "label": "Toggle Layer"},
    "layer_rude_toggle": {"prefix": "TO_LAYER_", "label": "Force Layer"},
    "layer_polite_oneshot": {"prefix": "STICKY_LAYER_", "label": "Sticky Layer"},
}

# Behavior slots. "Tap" is the primary (stored as 'tap'; legacy 'press' reads as
# 'tap'). Tap + Hold are wired now; the richer Dygma-style "superkey" slots are
# legitimate ZMK behaviours we can build out later.
BEHAVIOR_SLOTS = [
    {"id": "tap", "label": "Tap", "enabled": True},
    {"id": "hold", "label": "Hold", "enabled": True},
    {"id": "double_tap", "label": "Double Tap", "enabled": False},
    {"id": "tap+hold", "label": "Tap + Hold", "enabled": False},
    {"id": "double_tap+hold", "label": "Double Tap + Hold", "enabled": False},
]


def _a(code, label, action_type="key", coming_soon=False):
    d = {"code": code, "label": label, "actionType": action_type}
    if coming_soon:
        d["comingSoon"] = True
    return d


def _letters():
    return [_a(c, c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]


def _numbers():
    shift = {0: "0", 1: "1 !", 2: "2 @", 3: "3 #", 4: "4 $", 5: "5 %",
             6: "6 ^", 7: "7 &", 8: "8 *", 9: "9 (", }
    return [_a(f"NUMBER_{n}", shift[n]) for n in range(10)]


def _modifiers():
    return [
        _a("LCTRL", "L-Ctrl", "modifier"), _a("RCTRL", "R-Ctrl", "modifier"),
        _a("LSHIFT", "L-Shift", "modifier"), _a("RSHIFT", "R-Shift", "modifier"),
        _a("LALT", "L-Alt", "modifier"), _a("RALT", "R-Alt", "modifier"),
        _a("LGUI", "L-Win", "modifier"), _a("RGUI", "R-Win", "modifier"),
    ]


def _symbols():
    syms = {
        "GRAVE": "` ~", "MINUS": "- _", "EQUAL": "= +", "LEFT_BRACKET": "[ {",
        "RIGHT_BRACKET": "] }", "BACKSLASH": "\\ |", "SEMICOLON": "; :",
        "SINGLE_QUOTE": "' \"", "COMMA": ", <", "PERIOD": ". >", "SLASH": "/ ?",
        "EXCLAMATION": "!", "AT_SIGN": "@", "HASH": "#", "DOLLAR": "$",
        "PERCENT": "%", "CARET": "^", "AMPERSAND": "&", "ASTERISK": "*",
        "LEFT_PARENTHESIS": "(", "RIGHT_PARENTHESIS": ")", "UNDERSCORE": "_",
        "PLUS": "+", "LEFT_BRACE": "{", "RIGHT_BRACE": "}", "PIPE": "|",
        "COLON": ":", "DOUBLE_QUOTES": "\"", "LESS_THAN": "<", "GREATER_THAN": ">",
        "QUESTION": "?", "TILDE": "~",
    }
    return [_a(c, l) for c, l in syms.items()]


def _mouse():
    return [
        _a("M1", "L Click", "mouse"), _a("M2", "R Click", "mouse"),
        _a("M3", "M Click", "mouse"), _a("M4", "Mouse 4", "mouse"),
        _a("M5", "Mouse 5", "mouse"),
    ]


def _connection():
    return [
        _a("BT_DEVICE_1", "BT 1", "bluetooth"), _a("BT_DEVICE_2", "BT 2", "bluetooth"),
        _a("BT_DEVICE_3", "BT 3", "bluetooth"), _a("BT_DEVICE_4", "BT 4", "bluetooth"),
        _a("BT_CLEAR", "BT Clear", "bluetooth"),
        _a("BT_OUT", "Wireless", "out"), _a("USB_DEVICE", "USB-C", "out"),
    ]


def _system():
    return [
        _a("C_BRIGHTNESS_INC", "Bright +"), _a("C_BRIGHTNESS_DEC", "Bright -"),
        _a("C_VOL_UP", "Vol +"), _a("C_VOL_DOWN", "Vol -"), _a("C_MUTE", "Mute"),
        _a("C_PLAY_PAUSE", "Play/Pause"), _a("C_NEXT", "Next"),
        _a("C_PREVIOUS", "Prev"), _a("C_FAST_FORWARD", "FF"), _a("C_REWIND", "Rew"),
        _a("PRINTSCREEN", "PrtScn"), _a("C_POWER", "Power"),
    ]


def _keypad():
    out = [_a(f"KP_NUMBER_{n}", str(n)) for n in range(10)]
    out += [
        _a("KP_PLUS", "+"), _a("KP_MINUS", "-"), _a("KP_MULTIPLY", "×"),
        _a("KP_DIVIDE", "÷"), _a("KP_DOT", "."), _a("KP_ENTER", "Enter"),
        _a("KP_NUMLOCK", "Num Lk"),
    ]
    return out


def _navigation():
    return [
        _a("UP", "↑"), _a("DOWN", "↓"), _a("LEFT", "←"), _a("RIGHT", "→"),
        _a("HOME", "Home"), _a("END", "End"), _a("PG_UP", "PgUp"),
        _a("PG_DN", "PgDn"), _a("K_APP", "Menu"),
    ]


def _international():
    out = [_a(f"LANG{n}", f"Lang {n}") for n in range(1, 10)]
    out += [_a(f"INT{n}", f"Int {n}") for n in range(1, 7)]
    out += [_a("NON_US_BACKSLASH", "\\ |"), _a("NON_US_HASH", "# ~")]
    return out


def _locks():
    return [
        _a("CAPSLOCK", "Caps Lk"), _a("KP_NUMLOCK", "Num Lk"),
        _a("SCROLLLOCK", "Scroll Lk"), _a("PAUSE_BREAK", "Pause"),
    ]


def _function():
    return [_a(f"F{n}", f"F{n}") for n in range(1, 25)]


def _empty():
    return [
        _a("TRANSPARENT", "Transparent", "trans"),
        _a("DISABLE", "Disabled", "none"),
    ]


def _recovery():
    # Naya-custom "recover module from critical battery drain". Almost certainly a
    # firmware-recovery mode; parked as coming-soon until we understand it on device.
    return [_a("MODULE_FORCE_CHARGING", "Recover Module", "naya", coming_soon=True)]


# Common OS/editor shortcuts as shortcut_alias combos. Representative set; the full
# NayaFlow catalog (from ZMK/OS presets) can be expanded from flow-strings.txt.
def _mac_shortcuts():
    combos = {
        "LGUI + C": "Copy", "LGUI + V": "Paste", "LGUI + X": "Cut",
        "LGUI + Z": "Undo", "LGUI + LSHIFT + Z": "Redo", "LGUI + A": "Select All",
        "LGUI + S": "Save", "LGUI + F": "Find", "LGUI + TAB": "App Switch",
        "LGUI + SPACE": "Spotlight", "LGUI + LCTRL + F": "Fullscreen",
    }
    return [_a(c, l, "shortcut_alias") for c, l in combos.items()]


def _win_shortcuts():
    combos = {
        "LCTRL + C": "Copy", "LCTRL + V": "Paste", "LCTRL + X": "Cut",
        "LCTRL + Z": "Undo", "LCTRL + Y": "Redo", "LCTRL + A": "Select All",
        "LCTRL + S": "Save", "LCTRL + F": "Find", "LALT + TAB": "App Switch",
        "LGUI + D": "Show Desktop", "LGUI + LSHIFT + S": "Screenshot",
    }
    return [_a(c, l, "shortcut_alias") for c, l in combos.items()]


def _vscode_shortcuts():
    combos = {
        "LCTRL + LSHIFT + P": "Command Palette", "LCTRL + P": "Quick Open",
        "LCTRL + B": "Toggle Sidebar", "LCTRL + GRAVE": "Terminal",
        "LCTRL + SLASH": "Comment", "LALT + UP": "Move Line Up",
        "LALT + DOWN": "Move Line Down", "LCTRL + D": "Add Selection",
        "LCTRL + LSHIFT + K": "Delete Line", "F2": "Rename",
    }
    return [_a(c, l, "shortcut_alias") for c, l in combos.items()]


def _tabs():
    return [
        {"id": "basic", "label": "B", "title": "Basic keys", "categories": [
            {"name": "Letters", "actions": _letters()},
            {"name": "Numbers", "actions": _numbers()},
            {"name": "Modifiers", "actions": _modifiers()},
            {"name": "Symbols", "actions": _symbols()},
        ]},
        {"id": "extended", "label": "+", "title": "Extended", "categories": [
            {"name": "Empty", "actions": _empty()},
            {"name": "Mouse", "actions": _mouse()},
            {"name": "Connection", "actions": _connection()},
            {"name": "Recovery", "actions": _recovery()},
            {"name": "System", "actions": _system()},
            {"name": "Keypad", "actions": _keypad()},
            {"name": "Navigation", "actions": _navigation()},
            {"name": "International", "actions": _international()},
            {"name": "Locks", "actions": _locks()},
            {"name": "Function Keys", "actions": _function()},
        ]},
        {"id": "layers", "label": "✦", "title": "Layers", "categories": []},
        {"id": "shortcuts", "label": "↗", "title": "Shortcuts", "categories": [
            {"name": "MacOS", "actions": _mac_shortcuts()},
            {"name": "Windows", "actions": _win_shortcuts()},
            {"name": "VS Code Presets", "actions": _vscode_shortcuts()},
        ]},
    ]


def get_catalog() -> dict:
    return {
        "tabs": _tabs(),
        "behaviorSlots": BEHAVIOR_SLOTS,
        "layerActionTypes": [
            {"frontendType": k, **v} for k, v in LAYER_ACTION_TYPES.items()
        ],
    }
