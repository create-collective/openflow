"""The action palette — what a user can bind to a key.

Assembled from the recovered NayaFlow action catalog (device-constants.txt, the
flow-strings.txt catalog records, and action-icons.json). Action *codes* are
functional facts (they must match what the firmware/DB expect); labels here are
OpenFlow's own concise descriptions (clean reskin).

`actionType` values match what NayaFlow stored in key_bindings.action_type
(key / modifier / LED / bluetooth / out / none / naya), so data round-trips.
Layer-switch actions are handled separately (they embed a target layer id) — see
LAYER_ACTION_TYPES.
"""

from __future__ import annotations

# action_type -> ZMK behaviour (reference; from device-constants.txt lines 226-233)
ZMK_BEHAVIOUR = {
    "KEY_PRESS": "&kp",
    "MOD_TAP": "&mt",
    "TO_LAYER": "&to",
    "TOGGLE_LAYER": "&tog",
    "STICKY_LAYER": "&sl",
    "MO": "&mo",
    "RGB_UG": "&rgb_ug",
    "BLUETOOTH": "&bt",
    "OUTPUTS": "&out",
}

# frontendType -> (action_code prefix, DB action_type) for layer-switch keys
LAYER_ACTION_TYPES = {
    "layer_polite_hold": {"prefix": "MO_LAYER_", "label": "Hold for layer"},
    "layer_rude_toggle": {"prefix": "TO_LAYER_", "label": "Go to layer"},
    "layer_polite_toggle": {"prefix": "TOGGLE_LAYER_", "label": "Toggle layer"},
    "layer_polite_oneshot": {"prefix": "STICKY_LAYER_", "label": "Sticky layer"},
}

BEHAVIOR_SLOTS = [
    {"id": "press", "label": "Press"},
    {"id": "tap", "label": "Tap"},
    {"id": "double_tap", "label": "Double Tap"},
    {"id": "hold", "label": "Hold"},
    {"id": "tap+hold", "label": "Tap + Hold"},
]


def _a(code, label, category, action_type="key"):
    return {"code": code, "label": label, "category": category, "actionType": action_type}


def _build() -> list[dict]:
    items: list[dict] = []

    # Alphanumeric — letters
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        items.append(_a(c, c, "Alphanumeric"))
    # Alphanumeric — numbers
    num_shift = {0: "0", 1: "1 !", 2: "2 @", 3: "3 #", 4: "4 $", 5: "5 %",
                 6: "6 ^", 7: "7 &", 8: "8 *", 9: "9 ("}
    for n in range(10):
        items.append(_a(f"NUMBER_{n}", num_shift[n], "Alphanumeric"))

    # Symbols and Punctuation
    symbols = {
        "GRAVE": "` ~", "MINUS": "- _", "EQUAL": "= +", "LEFT_BRACKET": "[ {",
        "RIGHT_BRACKET": "] }", "BACKSLASH": "\\ |", "SEMICOLON": "; :",
        "SINGLE_QUOTE": "' \"", "COMMA": ", <", "PERIOD": ". >", "SLASH": "/ ?",
        "LEFT_PARENTHESIS": "(", "RIGHT_PARENTHESIS": ")", "LEFT_BRACE": "{",
        "RIGHT_BRACE": "}", "AMPERSAND": "&", "ASTERISK": "*", "AT_SIGN": "@",
        "CARET": "^", "COLON": ":", "DOLLAR": "$", "DOUBLE_QUOTES": "\"",
        "EXCLAMATION": "!", "GREATER_THAN": ">", "HASH": "#", "LESS_THAN": "<",
        "PERCENT": "%", "PIPE": "|", "PLUS": "+", "QUESTION": "?", "TILDE": "~",
        "UNDERSCORE": "_", "NON_US_BACKSLASH": "\\ (Non-US)",
    }
    for code, label in symbols.items():
        items.append(_a(code, label, "Symbols"))

    # Numpad
    for n in range(10):
        items.append(_a(f"KP_NUMBER_{n}", f"Keypad {n}", "Numpad"))
    for code, label in {
        "KP_DIVIDE": "Keypad /", "KP_MULTIPLY": "Keypad *", "KP_MINUS": "Keypad -",
        "KP_PLUS": "Keypad +", "KP_DOT": "Keypad .", "KP_ENTER": "Keypad Enter",
        "KP_EQUAL": "Keypad =", "KP_NUMLOCK": "Num Lock",
    }.items():
        items.append(_a(code, label, "Numpad"))

    # Function keys
    for n in range(1, 25):
        items.append(_a(f"F{n}", f"F{n}", "Function"))

    # Modifiers
    mods = {
        "LCTRL": "Control", "LSHIFT": "Shift", "LALT": "Alt", "LGUI": "Meta",
        "RCTRL": "Right Control", "RSHIFT": "Right Shift", "RALT": "Right Alt",
        "RGUI": "Right Meta",
    }
    for code, label in mods.items():
        items.append(_a(code, label, "Modifiers", action_type="modifier"))

    # Locks
    for code, label in {"CAPSLOCK": "Caps Lock", "SCROLLLOCK": "Scroll Lock",
                        "PAUSE_BREAK": "Pause / Break"}.items():
        items.append(_a(code, label, "Modifiers"))

    # System — control
    for code, label in {"RETURN": "Enter", "SPACE": "Space", "TAB": "Tab",
                        "BACKSPACE": "Backspace", "DELETE": "Delete", "ESC": "Escape",
                        "INSERT": "Insert", "PRINTSCREEN": "Print Screen"}.items():
        items.append(_a(code, label, "System"))
    # System — navigation
    for code, label in {"UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
                        "HOME": "Home", "END": "End", "PG_UP": "Page Up",
                        "PG_DN": "Page Down", "K_APP": "Menu"}.items():
        items.append(_a(code, label, "System"))
    # System — media (consumer keys)
    for code, label in {"C_MUTE": "Mute", "C_VOL_UP": "Volume Up",
                        "C_VOL_DOWN": "Volume Down", "C_PLAY_PAUSE": "Play / Pause",
                        "C_NEXT": "Next Track", "C_PREVIOUS": "Previous Track",
                        "C_FAST_FORWARD": "Fast Forward", "C_REWIND": "Rewind",
                        "C_BRIGHTNESS_INC": "Brightness Up",
                        "C_BRIGHTNESS_DEC": "Brightness Down",
                        "C_POWER": "Power"}.items():
        items.append(_a(code, label, "System"))

    # International
    for n in range(1, 7):
        items.append(_a(f"INT{n}", f"International {n}", "International"))
    for n in range(1, 10):
        items.append(_a(f"LANG{n}", f"Language {n}", "International"))

    # Lighting (LED)
    for code, label in {
        "LED_EFFECT_ON_OFF": "LED On/Off", "LED_EFFECT": "Cycle Effect",
        "LED_SOLID": "Solid", "LED_BREATHE": "Breathe", "LED_SWIRL": "Swirl",
        "LED_SPEC": "Spectrum", "LED_BRIGHTNESS_UP": "Brightness Up",
        "LED_BRIGHTNESS_DOWN": "Brightness Down", "LED_SPEED_UP": "Speed Up",
        "LED_SPEED_DOWN": "Speed Down", "LED_COLOR_WHITE": "White",
        "LED_COLOR_RED": "Red", "LED_COLOR_GREEN": "Green", "LED_COLOR_BLUE": "Blue",
    }.items():
        items.append(_a(code, label, "Lighting", action_type="LED"))

    # Connection
    for n in range(1, 5):
        items.append(_a(f"BT_DEVICE_{n}", f"Bluetooth Device {n}", "Connection", action_type="bluetooth"))
    items.append(_a("BT_CLEAR", "Clear & Pair Bluetooth", "Connection", action_type="bluetooth"))
    items.append(_a("BT_OUT", "Connect Wireless", "Connection", action_type="out"))
    items.append(_a("USB_DEVICE", "Connect USB", "Connection", action_type="out"))

    # Empty
    items.append(_a("DISABLE", "Disabled", "Empty", action_type="none"))

    return items


CATALOG = _build()

CATEGORY_ORDER = [
    "Alphanumeric", "Symbols", "Numpad", "Function", "Modifiers",
    "System", "International", "Lighting", "Connection", "Empty",
]


def get_catalog() -> dict:
    """The full palette, grouped by category, plus behavior slots + layer types."""
    by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORY_ORDER}
    for item in CATALOG:
        by_cat.setdefault(item["category"], []).append(item)
    return {
        "categories": [
            {"name": c, "actions": by_cat[c]} for c in CATEGORY_ORDER if by_cat.get(c)
        ],
        "behaviorSlots": BEHAVIOR_SLOTS,
        "layerActionTypes": [
            {"frontendType": k, **v} for k, v in LAYER_ACTION_TYPES.items()
        ],
    }
