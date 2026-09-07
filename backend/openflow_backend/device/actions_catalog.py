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

# Behavior slots (the "OneKey" multi-behavior-per-key feature). "Tap" is the
# primary (stored as 'tap'; legacy 'press' reads as 'tap'). Tap/Hold/Double Tap/
# Tap+Hold are editable and stored offline in the DB; flashing them to the device
# waits on the REMAP layer-data codec. Double Tap+Hold stays experimental — it may
# exceed Naya's firmware and belongs to the fully-open OneKey firmware track.
# Tap and Hold are the only slots Naya's firmware actually stores + honors. A live
# read + reflash test (2026-09-01) proved NayaFlow drops Double Tap and Tap + Hold on
# flash — they're half-finished firmware slots — so they're disabled + flagged
# experimental like Double Tap + Hold until the open OneKey firmware lands.
# A key holds FOUR behaviours, stored as TWO hold-tap records 0x52 apart: the primary bank is
# tap + hold, the secondary bank is double-tap + tap+hold. Confirmed live 2026-09-03 by capturing
# NayaFlow writing both records and then pressing the key (b / zzz / x / yyy). Read, write and
# round-trip are covered by tests/test_second_bank.py and test_four_behaviour_roundtrip.py.
#
# "Double Tap + Hold" stays disabled: there is no third bank and nothing has ever been observed
# writing it, so it is not known to exist.
BEHAVIOR_SLOTS = [
    {"id": "tap", "label": "Tap", "enabled": True},
    {"id": "hold", "label": "Hold", "enabled": True},
    {"id": "double_tap", "label": "Double Tap", "enabled": True},
    {"id": "tap_hold", "label": "Tap + Hold", "enabled": True},
    {"id": "double_tap+hold", "label": "Double Tap + Hold", "enabled": False},
]


def _a(code, label, action_type="key", coming_soon=False, name=None):
    """One palette entry.

    `label` is the keycap legend and stays terse -- a palette button is a 44px grid cell that
    clips "Left Click" where "L Click" fits. `name` is the optional sentence-case form for
    tooltips and for anywhere the value is shown as prose rather than on a key.
    """
    d = {"code": code, "label": label, "actionType": action_type}
    if coming_soon:
        d["comingSoon"] = True
    if name:
        d["name"] = name
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


def _control():
    return [
        _a("RETURN", "Enter"), _a("ESC", "Esc"), _a("BACKSPACE", "Bksp"),
        _a("DELETE", "Del"), _a("TAB", "Tab"), _a("SPACE", "Space"), _a("INSERT", "Ins"),
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


# Full OS/editor shortcut presets, extracted verbatim from NayaFlow's recovered
# catalog (flow-strings.txt). action_code is the literal combo NayaFlow stored
# (shortcut_alias). Lists (not dicts) so duplicate combos are preserved.
_MAC = [
    ("LGUI + X", "Cut"), ("LGUI + C", "Copy"), ("LGUI + V", "Paste"), ("LGUI + Z", "Undo"),
    ("LSHIFT + LGUI + Z", "Redo"), ("LGUI + A", "Select All"), ("LGUI + F", "Find"),
    ("LSHIFT + LGUI + G", "Find Previous"), ("LGUI + G", "Find Next"), ("LGUI + SPACE", "Spotlight"),
    ("LALT + LGUI + SPACE", "Spotlight From Finder"), ("LGUI + H", "Hide"),
    ("LALT + LGUI + H", "Hide Other Apps"), ("LGUI + M", "Minimize Front Window"),
    ("LALT + LGUI + M", "Minimize All Windows of App"), ("LCTRL + LGUI + F", "Fullscreen"),
    ("LGUI + O", "Open"), ("LGUI + P", "Print"), ("LGUI + S", "Save"),
    ("LCTRL + LGUI + SPACE", "Character Viewer"), ("LGUI + T", "New Tab"),
    ("LCTRL + TAB", "Next Tab"), ("LCTRL + LSHIFT + TAB", "Prev Tab"), ("LGUI + W", "Close Window"),
    ("LALT + LGUI + W", "Close All Windows of Application"),
    ("LGUI + GRAVE", "Switch to Previous Window"), ("LSHIFT + LGUI + GRAVE", "Switch to Next Window"),
    ("LGUI + Q", "Quit Application"), ("LALT + LGUI + ESC", "Force Quit Application"),
    ("LGUI + TAB", "Switch to Previous App"), ("LSHIFT + LGUI + TAB", "Switch to Next App"),
    ("LCTRL + LEFT", "Switch to Previous Screen"), ("LCTRL + RIGHT", "Switch to Next Screen"),
    ("LSHIFT + LGUI + NUMBER_3", "Screenshot"), ("LSHIFT + LGUI + NUMBER_5", "Open Screenshot Dialog"),
    ("LSHIFT + LGUI + NUMBER_4", "Screenshot Cursor"),
    ("LALT + LSHIFT + LGUI + NUMBER_4", "Screenshot Cursor Clipboard"),
    ("LSHIFT + LGUI + N", "New Folder"), ("LCTRL + LGUI + N", "New Folder with Selection"),
    ("LGUI + COMMA", "Open Preferences"), ("LALT + LSHIFT + LGUI + Q", "Log Out Mac"),
    ("LCTRL + LSHIFT + C_POWER", "Display Sleep"), ("LCTRL + UP", "Mission Control"),
    ("LCTRL + DOWN", "App Expose"),
]
_WIN = [
    ("LCTRL + X", "Cut to clipboard"), ("LCTRL + C", "Copy to clipboard"),
    ("LCTRL + V", "Paste from clipboard"), ("LCTRL + LSHIFT + V", "Paste as plain text"),
    ("LCTRL + B", "Apply bold format"), ("LCTRL + I", "Apply italic format"),
    ("LCTRL + U", "Apply underline format"), ("LCTRL + BACKSPACE", "Delete words to the left"),
    ("LCTRL + DELETE", "Delete words to the right"), ("LCTRL + LEFT", "Move to previous word"),
    ("LCTRL + RIGHT", "Move to next word"), ("LCTRL + UP", "Move to previous paragraph"),
    ("LCTRL + DOWN", "Move to next paragraph"), ("LCTRL + HOME", "Move to beginning of document"),
    ("LCTRL + END", "Move to end of document"), ("LCTRL + F", "Find text"),
    ("LCTRL + H", "Find and replace text"), ("LCTRL + A", "Select all"),
    ("LSHIFT + LEFT", "Select characters backward"), ("LSHIFT + RIGHT", "Select characters forward"),
    ("LSHIFT + LCTRL + LEFT", "Select words backward"), ("LSHIFT + LCTRL + RIGHT", "Select words forward"),
    ("LSHIFT + HOME", "Select to beginning of line"), ("LSHIFT + END", "Select to end of line"),
    ("LSHIFT + UP", "Select lines backward"), ("LSHIFT + DOWN", "Select lines forward"),
    ("LSHIFT + LCTRL + UP", "Select paragraphs backward"),
    ("LSHIFT + LCTRL + DOWN", "Select paragraphs forward"), ("LSHIFT + PG_UP", "Select one page backward"),
    ("LSHIFT + PG_DN", "Select one page forward"), ("LSHIFT + LCTRL + HOME", "Select to beginning of document"),
    ("LSHIFT + LCTRL + END", "Select to end of document"), ("LALT + A", "Set focus to Suggested actions"),
    ("LALT + TAB", "Switch to previous app"), ("LALT + LSHIFT + TAB", "Switch to next app"),
    ("LALT + F4", "Close active item"), ("LALT + LSHIFT + ESC", "Previous window"),
    ("LALT + ESC", "Next window"), ("LCTRL + LSHIFT + TAB", "Previous tab"), ("LCTRL + TAB", "Next tab"),
    ("LCTRL + T", "New tab"), ("LCTRL + F4", "Close active document"),
    ("LGUI + LCTRL + D", "Add a virtual desktop"), ("LGUI + LCTRL + LEFT", "Switch to left virtual desktop"),
    ("LGUI + LCTRL + RIGHT", "Switch to right virtual desktop"), ("LALT + PG_DN", "Move down one screen"),
    ("LALT + PG_UP", "Move up one screen"), ("LGUI + LCTRL + F4", "Close virtual desktop"),
    ("LCTRL + Z", "Undo an action"), ("LCTRL + Y", "Redo an action"), ("LALT + F8", "Show password"),
    ("LALT + SPACE", "Open context menu"), ("LALT + LEFT", "Go back"), ("LALT + RIGHT", "Go forward"),
    ("LCTRL + LSHIFT + ESC", "Open Task Manager"), ("LGUI + TAB", "Open Task view"),
    ("LALT + ENTER", "Display properties"), ("LGUI + I", "Open Settings"),
]
_VSCODE = [
    ("LALT + UP", "Move Line Up"), ("LALT + DOWN", "Move Line Down"),
    ("LSHIFT + LALT + UP", "Copy Line Up"), ("HOME", "Go to Line Start"), ("END", "Go to Line End"),
    ("LCTRL + DOWN", "Scroll Line Down"), ("LCTRL + UP", "Scroll Line Up"),
    ("LALT + PG_DN", "Scroll Page Down"), ("LALT + PG_UP", "Scroll Page Up"),
    ("LALT + Z", "Toggle Word Wrap"), ("F12", "Go to Definition"), ("LSHIFT + F12", "Show References"),
    ("F2", "Rename Symbol"), ("LSHIFT + LALT + I", "Insert Cursor at End of Line"),
    ("LCTRL + L", "Select Current Line"), ("LSHIFT + LALT + LEFT", "Shrink Selection"),
    ("LSHIFT + LALT + RIGHT", "Expand Selection"), ("LALT + ENTER", "Select All Find Matches"),
    ("LSHIFT + F8", "Go to Previous Error"), ("F8", "Go to Next Error"),
    ("LCTRL + LSHIFT + TAB", "Open Previous"), ("LCTRL + TAB", "Open Next"), ("F9", "Toggle Breakpoint"),
    ("F5", "Start / Continue"), ("LSHIFT + F5", "Stop"), ("F11", "Step Into"),
    ("LSHIFT + F11", "Step Out"), ("F10", "Step Over"), ("LCTRL + GRAVE", "Open Terminal"),
    ("LCTRL + LSHIFT + GRAVE", "Create Terminal"),
]


# NayaFlow spellings that differ from the entries above. Verified 2026-09-01 by pairing
# a NayaFlow user-data.db with the WRITE_LAYER_DATA frames NayaCore actually flashed
# (device/out/flash2-shortcut-dictionary.md): NayaFlow's own encoder drops a bracketed
# modifier entirely ("[LALT] + TAB" reaches the device as a plain Tab) and cannot
# encode CLICK or ENTER (both flash as HID usage 0 with only the modifier bits set).
# Importers should map these to the canonical code; None = no keyboard equivalent.
NAYAFLOW_CODE_ALIASES = {
    "[LALT] + TAB": "LALT + TAB",
    "[LALT] + LSHIFT + TAB": "LALT + LSHIFT + TAB",
    "LALT + CLICK": None,  # VS Code "Insert Cursor" is a mouse action, not a key press
}
# "LALT + ENTER" stays verbatim in the lists above; the frontend dictionary aliases
# ENTER -> RETURN (keydict.js CODE_ALIASES) and the device encoder must emit usage 0x28.


def _shortcuts(pairs):
    return [_a(code, label, "shortcut_alias") for code, label in pairs]


# Where a tab may appear. "key" is the Bindings keymap editor, "module" is a module gesture.
# A tab with no `contexts` is treated as both, so an author who forgets is visible rather than
# silently hidden -- but tests/test_actions_catalog.py fails on an undeclared tab, so it does
# not stay that way.
KEY, MODULE = "key", "module"


# Display order for the module-action groups. The list carries 13 groups and a bare
# alphabetical sort buries the ones you reach for -- clicks and motion are what a gesture is
# usually bound to, and caret editing is the biggest group but the most specialised.
_MODULE_GROUP_ORDER = [
    "Clicks", "Cursor", "Scroll", "Media", "Tabs & browser", "Windows & desktops",
    "App navigation", "Clipboard & text", "Caret & selection", "Find", "Function keys",
    "Display & LED",
]


def _module_categories():
    """The module action vocabulary, bucketed by the group each action already carries.

    These 102 actions were only ever reachable through the per-gesture dropdown -- one flat
    list, no grouping, no tooltips. They are the vocabulary that is actually about a module
    (scroll, cursor, media, window management), so they belong in the palette beside the
    keyboard tabs rather than hidden in a select.
    """
    from .module_actions import MODULE_ACTIONS

    buckets: dict[str, list] = {}
    for a in MODULE_ACTIONS:
        if not a.get("code"):
            continue                        # the "None" entry: the row's own control clears it
        buckets.setdefault(a.get("group") or "Other", []).append(
            {"code": a["code"], "label": a["label"], "actionType": a["actionType"],
             "name": a.get("name") or a["label"]})
    ordered = [g for g in _MODULE_GROUP_ORDER if g in buckets]
    ordered += sorted(g for g in buckets if g not in _MODULE_GROUP_ORDER)
    return [{"name": g, "actions": buckets[g]} for g in ordered]


def _tabs():
    return [
        {"id": "basic", "label": "B", "title": "Basic keys", "contexts": [KEY, MODULE],
         "categories": [
            {"name": "Letters", "actions": _letters()},
            {"name": "Numbers", "actions": _numbers()},
            {"name": "Modifiers", "actions": _modifiers()},
            {"name": "Control", "actions": _control()},
            {"name": "Symbols", "actions": _symbols()},
        ]},
        # Module-only, and that is not an oversight. A mouse action on a KEY position never
        # reaches the device -- a key takes record type 0x00 with the same two-u32 body, but
        # its category namespace differs (category 3 is BLUETOOTH on a key and mouse buttons on
        # a module), and we have no capture of what a key uses for mouse. Offering it on
        # Bindings would offer a binding that silently never flashes.
        {"id": "mouse", "label": "●", "title": "Mouse",
         "contexts": [MODULE], "categories": []},
        # 5,311 chords across 20 applications. No categories: it has its own render branch,
        # because a searchable list of five thousand entries is not a grid of buttons. Visible
        # in BOTH contexts -- an app shortcut is just a chord, and a keycap can hold one as
        # readily as a gesture can.
        {"id": "apps", "label": "⌘", "title": "Application shortcuts",
         "contexts": [KEY, MODULE], "categories": []},
        # Module-only: these are gesture actions, and offering them on a keycap would be
        # offering bindings the keymap encoder has no field for.
        {"id": "module", "label": "◎", "title": "Module actions", "contexts": [MODULE],
         "categories": _module_categories()},
        {"id": "extended", "label": "+", "title": "Extended", "contexts": [KEY, MODULE],
         "categories": [
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
        {"id": "layers", "label": "✦", "title": "Layers", "contexts": [KEY],
         "categories": []},
        {"id": "shortcuts", "label": "↗", "title": "Shortcuts", "contexts": [KEY, MODULE],
         "categories": [
            {"name": "MacOS", "actions": _shortcuts(_MAC)},
            {"name": "Windows", "actions": _shortcuts(_WIN)},
            {"name": "VS Code Presets", "actions": _shortcuts(_VSCODE)},
        ]},
    ]


def get_catalog() -> dict:
    from . import shortcuts as _sc

    return {
        "tabs": _tabs(),
        "behaviorSlots": BEHAVIOR_SLOTS,
        "layerActionTypes": [
            {"frontendType": k, **v} for k, v in LAYER_ACTION_TYPES.items()
        ],
        # code -> {name, chord, icon, group, platform}. The UI showed raw chords like
        # "LALT + LSHIFT + ESC", which say what to press and nothing about what it does; this
        # lets a keycap, a gesture row or a tooltip say "Cycle windows backwards" instead.
        "shortcuts": {s["code"]: {k: s[k] for k in ("name", "chord", "icon", "group", "platform")
                                  if k in s}
                      for s in _sc.all_shortcuts()},
    }
