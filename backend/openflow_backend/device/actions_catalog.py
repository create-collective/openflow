"""The action palette — what a user can bind to a key.

Organized into the tabs NayaFlow uses:
  - "B" (basic):    Letters, Numbers, Modifiers, Symbols
  - "+" (extended): Empty (Transparent/Disable), Mouse, Connection, Recovery,
                    System, Keypad, Navigation, International, Locks, Function
  - "✦" (layers):   Hold / Toggle / Force / Sticky layer (bound to a target layer)
  - "↗" (shortcuts):MacOS / Windows / VS Code presets

Action *codes* are functional facts (must match firmware/DB); labels are OpenFlow's
own (clean reskin). `actionType` matches NayaFlow's key_bindings.action_type so data
round-trips.
"""

from __future__ import annotations

import json
from pathlib import Path

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
# primary (stored as 'tap'; legacy 'press' reads as 'tap').
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


def _a(code, label, action_type="key", name=None):
    """One palette entry.

    `label` is the keycap legend and stays terse -- a palette button is a 44px grid cell that
    clips "Left Click" where "L Click" fits. `name` is the optional sentence-case form for
    tooltips and for anywhere the value is shown as prose rather than on a key.
    """
    d = {"code": code, "label": label, "actionType": action_type}
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
        # Confirmed 2026-09-08: BT_CLEAR writes a real record, two-param (0, 0). We had inferred
        # from a stock board -- where that position happened to be unbound -- that NayaCore did
        # not flash it either. Absence of evidence.
        _a("BT_CLEAR", "BT Clear", "bluetooth", name="Clear the Bluetooth pairing"),
        # Beyond NayaFlow: its UI never offers these, but NayaCore's own Bluetooth table defines
        # them (ZMK &bt next / previous) and the same table's clear and select rows match the
        # board. Never yet read off hardware.
        _a("BT_NEXT", "BT Next", "bluetooth", name="Next Bluetooth device"),
        _a("BT_PREV", "BT Prev", "bluetooth", name="Previous Bluetooth device"),
        _a("BT_OUT", "Wireless", "out"), _a("USB_DEVICE", "USB-C", "out"),
    ]


def _naya_system():
    """Naya's own system actions -- record type 0x06.

    Only one is known. It is the lightning key on the stock System layer (position 62), and its
    type was an unknown byte until a probe profile carried it and it read back as 0x06 with
    param 401."""
    return [
        _a("MODULE_FORCE_CHARGING", "Force charge", "naya",
           name="Force the docked modules to charge"),
    ]


def _lighting():
    """The LED system keys (record type 0x09, ZMK's &rgb_ug).

    These were readable but not bindable: the palette had no LED entries at all, so a board that
    came with fourteen lighting keys could be read and then never rebuilt. Codes and names are
    NayaFlow's own -- each was matched to a device record by flashing Naya's default profile and
    pairing the bytes with its database (2026-09-08). Decode/encode live in
    keymap_read.decode_rgb_system / remap.encode_rgb_system.
    """
    return [
        _a("LED_EFFECT_ON_OFF", "Lights", "LED", name="Lighting on / off"),
        _a("LED_EFFECT", "Effect", "LED", name="Next lighting effect"),
        _a("LED_SOLID", "Solid", "LED", name="Lighting: Solid"),
        _a("LED_BREATHE", "Breathe", "LED", name="Lighting: Breathe"),
        _a("LED_SWIRL", "Swirl", "LED", name="Lighting: Swirl"),
        _a("LED_SPEC", "Spectrum", "LED", name="Lighting: Spectrum"),
        _a("LED_BRIGHTNESS_UP", "Bright +", "LED", name="Lighting brightness up"),
        _a("LED_BRIGHTNESS_DOWN", "Bright -", "LED", name="Lighting brightness down"),
        _a("LED_SPEED_UP", "Speed +", "LED", name="Lighting effect speed up"),
        _a("LED_SPEED_DOWN", "Speed -", "LED", name="Lighting effect speed down"),
        _a("LED_COLOR_WHITE", "White", "LED", name="Lighting color: white"),
        _a("LED_COLOR_RED", "Red", "LED", name="Lighting color: red"),
        _a("LED_COLOR_GREEN", "Green", "LED", name="Lighting color: green"),
        _a("LED_COLOR_BLUE", "Blue", "LED", name="Lighting color: blue"),
        # The remaining five of NayaFlow's nine; bytes from NayaCore's own table (keymap_read).
        _a("LED_COLOR_CYAN", "Cyan", "LED", name="Lighting color: cyan"),
        _a("LED_COLOR_MAGENTA", "Magenta", "LED", name="Lighting color: magenta"),
        _a("LED_COLOR_YELLOW", "Yellow", "LED", name="Lighting color: yellow"),
        _a("LED_COLOR_ORANGE", "Orange", "LED", name="Lighting color: orange"),
        _a("LED_COLOR_PINK", "Pink", "LED", name="Lighting color: pink"),
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
    out += [_a("NON_US_BACKSLASH", "\\ |"), _a("NON_US_HASH", "# ~"),
            # NayaFlow's "| 2" and "~ 2": Shift + the two non-US keys (ZMK PIPE2 / TILDE2).
            _a("PIPE2", "| 2", name="Pipe (non-US)"), _a("TILDE2", "~ 2", name="Tilde (non-US)")]
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
    # NayaFlow's own two entries for the same pair. A bracketed modifier is one the user is
    # already holding, so these flash as a bare Tab / Shift+Tab (captured: 2b000700 / 2b000702)
    # and step through an app switcher that is already open. Different bytes from the two
    # above, which press Alt for you; both are offered.
    ("[LALT] + TAB", "Switch to previous app (Alt held)"),
    ("[LALT] + LSHIFT + TAB", "Switch to next app (Alt held)"),
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
    # NayaFlow's "Insert Cursor". Not a keyboard usage: the device holds the modifier alone
    # (captured as 00000004) and the user supplies the click. It was left out of this list as
    # "a mouse action, not a key press"; it is a chord NayaFlow binds to a key, and the encoder
    # writes exactly what NayaCore writes for it (remap.MODIFIER_ONLY_BASES).
    ("LALT + CLICK", "Insert Cursor"),
]
# NayaFlow's "VS Code Presets (Mac)" group -- 57 chords, macOS only in its UI. Missing here until
# the 2026-09-09 coverage probe (tools/action_coverage.py) listed every one of them as bindable
# in NayaFlow and absent from this palette. Codes and names are the vendor catalog's own
# (docs/reference/nayaflow-key-palette.json); "LGUI + CTRL + F" keeps its bare CTRL, which the
# encoder reads as LCTRL.
_VSCODE_MAC = [
    ("LGUI + LSHIFT + P", "Show Command Palette"), ("LGUI + LSHIFT + N", "New Window"),
    ("LGUI + LSHIFT + K", "Delete Line"), ("LGUI + LSHIFT + ENTER", "Insert Line Above"),
    ("LGUI + ENTER", "Insert Line Below"), ("LGUI + LSHIFT + BACKSLASH", "Jump to Bracket"),
    ("LGUI + LEFT_BRACKET", "Outdent Line"), ("LGUI + RIGHT_BRACKET", "Indent Line"),
    ("LGUI + UP", "Go to File Start"), ("LGUI + DOWN", "Go to File End"),
    ("LGUI + LSHIFT + LEFT_BRACKET", "Fold Region"), ("LGUI + LSHIFT + RIGHT_BRACKET", "Unfold Region"),
    ("LGUI + SLASH", "Toggle Line Comment"), ("LSHIFT + LALT + A", "Toggle Block Comment"),
    ("LGUI + LSHIFT + SPACE", "Trigger Parameter Hints"), ("LSHIFT + LALT + F", "Format Document"),
    ("LALT + F12", "Peek Definition"), ("LGUI + PERIOD", "Quick Fix"),
    ("LGUI + LALT + UP", "Insert Cursor Above"), ("LGUI + LALT + DOWN", "Insert Cursor Below"),
    ("LGUI + U", "Undo Cursor Operation"), ("LGUI + LSHIFT + L", "Select All Occurrences"),
    ("LGUI + F2", "Select All Word Occurrences"), ("LGUI + CTRL + F", "Toggle Full Screen"),
    ("LSHIFT + LGUI + NUMBER_0", "Toggle Editor Layout"), ("LGUI + MINUS", "Zoom Out"),
    ("LGUI + EQUAL", "Zoom In"), ("LGUI + B", "Toggle Sidebar"),
    ("LGUI + LSHIFT + E", "Show Explorer"), ("LGUI + LSHIFT + F", "Show Search"),
    ("LGUI + LSHIFT + G", "Show Source Control"), ("LGUI + LSHIFT + D", "Show Debug"),
    ("LGUI + LSHIFT + X", "Show Extensions"), ("LGUI + LSHIFT + H", "Replace in Files"),
    ("LGUI + LSHIFT + J", "Toggle Search Details"), ("LGUI + LSHIFT + U", "Show Output Panel"),
    ("LGUI + LSHIFT + V", "Open Markdown Preview"), ("LALT + LGUI + F", "Replace"),
    ("LGUI + D", "Add Selection to Next Find match"), ("LCTRL + P", "Go to File"),
    ("LGUI + LSHIFT + O", "Go to Symbol"), ("LGUI + LSHIFT + M", "Show Problems Panel"),
    ("LGUI + LSHIFT + TAB", "Navigate Editor History"), ("LGUI + LSHIFT + MINUS", "Go Forward"),
    ("LCTRL + LSHIFT + M", "Toggle Tab Moves Focus"), ("LGUI + BACKSLASH", "Split Editor"),
    ("LGUI + NUMBER_1", "Focus 1st Editor"), ("LGUI + NUMBER_2", "Focus 2nd Editor"),
    ("LGUI + NUMBER_3", "Focus 3rd Editor"), ("LGUI + N", "New File"),
    ("LGUI + LSHIFT + S", "Save As"), ("LALT + LGUI + S", "Save All"),
    ("LGUI + LSHIFT + T", "Reopen Closed Editor"), ("PAGE_UP", "Scroll Terminal Page Up"),
    ("PAGE_DOWN", "Scroll Terminal Page Down"), ("LGUI + HOME", "Scroll Terminal to Top"),
    ("LGUI + END", "Scroll Terminal to Bottom"),
]


# NayaFlow spellings that differ from the entries above. Verified 2026-09-01 by pairing
# a NayaFlow user-data.db with the WRITE_LAYER_DATA frames NayaCore actually flashed
# (device/out/flash2-shortcut-dictionary.md): NayaFlow's own encoder drops a bracketed
# modifier entirely ("[LALT] + TAB" reaches the device as a plain Tab) and stores CLICK and
# ENTER-less chords as HID usage 0 with only the modifier bits set. Our encoder does the same
# (remap.encode_keypress), so these are display aliases only; nothing maps to None any more.
NAYAFLOW_CODE_ALIASES = {
    "[LALT] + TAB": "LALT + TAB",
    "[LALT] + LSHIFT + TAB": "LALT + LSHIFT + TAB",
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


# Our shortcut dictionary, as it arrives inside MODULE_ACTIONS. These are plain chords -- a
# keycap can hold one exactly as a gesture can -- so they belong in the Shortcuts tab, which
# serves both contexts. They sat in the module-only tab, which meant "Close tab" could be bound
# to a Tune swipe but not to a key.
_CHORD_GROUPS = {"App navigation", "Caret & selection", "Clipboard & text", "Find",
                 "Function keys", "Tabs & browser", "Windows & desktops"}


def _module_categories(chords: bool = False):
    """The module action vocabulary, bucketed by the group each action already carries.

    These actions were only ever reachable through the per-gesture dropdown -- one flat list,
    no grouping, no tooltips -- so they belong in the palette beside the keyboard tabs.

    `chords` picks which half: False gives what only a MODULE can hold (cursor and scroll
    direction pairs, clicks, media, the LED keys), True gives the chord groups, which any
    keycap can hold too.
    """
    from .module_actions import MODULE_ACTIONS

    buckets: dict[str, list] = {}
    for a in MODULE_ACTIONS:
        if not a.get("code"):
            continue                        # the "None" entry: the row's own control clears it
        group = a.get("group") or "Other"
        if (group in _CHORD_GROUPS) != chords:
            continue
        entry = {"code": a["code"], "label": a["label"], "actionType": a["actionType"],
                 "name": a.get("name") or a["label"]}
        if a.get("nayaIcon"):
            entry["icon"] = a["nayaIcon"]   # NayaFlow's own name for this code wins in _describe
        buckets.setdefault(group, []).append(entry)
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
        # Visible in BOTH contexts as of 2026-09-07. This was module-only, on the reasoning that
        # a key's category namespace differed (category 3 being BLUETOOTH on a key). That was
        # wrong: bluetooth is a different RECORD TYPE (0x00), not a different category space.
        # Measured on hardware -- writing 0f 08 03000000 01000000 to layer 0 position 46 and
        # pressing the key produces a real left click, and ...02000000 a right click. A key takes
        # the same two-word record a module gesture does. See docs/module-field-map.md (C9/C10)
        # and tests/test_mouse_on_key.py, which pins the exact bytes.
        #
        # Buttons only on a key, though -- the frontend filters the four MOTION entries out of
        # the key context, because those are axis direction PAIRS ("mouse - SCROLL_UP -
        # SCROLL_DOWN") and a key position has no axis to bind them to.
        {"id": "mouse", "label": "●", "title": "Mouse",
         "contexts": [KEY, MODULE], "categories": []},
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
            {"name": "Lighting", "actions": _lighting()},
            {"name": "Naya system", "actions": _naya_system()},
            # "Recovery" used to sit here with the SAME action, MODULE_FORCE_CHARGING, parked as
            # coming-soon from before its record type was known. It has been readable and
            # writable (0x06, param 401) since 2026-09-08; the duplicate only made the palette
            # offer one bindable and one disabled button for a single key.
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
         # Ours first: hand-written, platform-tagged and grouped by what the chord DOES. The
         # four below are NayaFlow's presets, kept verbatim and grouped by the platform they
         # were written for.
         "categories": _module_categories(chords=True) + [
            {"name": "MacOS", "actions": _shortcuts(_MAC)},
            {"name": "Windows", "actions": _shortcuts(_WIN)},
            {"name": "VS Code Presets", "actions": _shortcuts(_VSCODE)},
            {"name": "VS Code Presets (Mac)", "actions": _shortcuts(_VSCODE_MAC)},
        ]},
    ]


# NayaFlow's own label and tooltip for every key action it offers, scraped from
# flow-bg-server.exe (tools/build_nayaflow_names.py -> nayaflow_names.json, 367 codes). These
# are the names a Naya owner already knows, so they are what the palette shows as an action's
# name and tooltip. Our terse `label` stays the keycap legend (a 44px cell), and our own
# sentence-case `name`, where one was written, survives as `alias` so search still finds it.
_NAMES_FILE = Path(__file__).with_name("nayaflow_names.json")


def nayaflow_names() -> dict:
    try:
        return json.loads(_NAMES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# Icons for the few entries that are ours, not NayaFlow's. The Windows Alt+Tab pair is the
# Windows twin of NayaFlow's Cmd+Tab pair, so it borrows those icons.
_ICON_OVERRIDES = {"LALT + TAB": "PREV_APP", "LALT + LSHIFT + TAB": "NEXT_APP"}


def _describe(action: dict, names: dict) -> dict:
    """One palette entry with NayaFlow's name and tooltip attached. Never drops a field."""
    out = dict(action)
    if action["code"] in _ICON_OVERRIDES:
        out["icon"] = _ICON_OVERRIDES[action["code"]]
    nf = names.get(action["code"])
    if not nf:
        if not out.get("name"):
            out["name"] = action["label"]
        return out

    # Whose name this entry carries, most specific source first. NayaFlow's vocabulary is one
    # GLOBAL name per chord and it is macOS- and editor-flavoured, so letting it win relabelled
    # things it knows nothing about: Ctrl+Up read as "Mission Control" (a macOS action; the
    # chord scrolls a line on Windows), Win+Tab as "Switch to Previous App" rather than Task
    # view, Alt+Tab's next and previous swapped, F11 reduced to "F11" -- and, worst of all, the
    # SAME name on all three preset categories, so one chord appeared three times as "Mission
    # Control" in a Windows search. The palette search ranks and displays this name, which is
    # how a tester searched for a macOS action and bound a Windows chord that scrolls
    # (SCRUM-83).
    #
    #   1. a name the entry set itself -- our shortcut dictionary, hand-written and
    #      platform-tagged;
    #   2. a shortcut preset's own label, which is written for ITS category ("Move to previous
    #      paragraph" under Windows, "Scroll Line Up" under VS Code);
    #   3. NayaFlow's global name, for everything else.
    # SCOPED TO SHORTCUT CHORDS. For device vocabulary -- LED effects, the Bluetooth keys, mouse
    # buttons -- NayaFlow's names are the better ones and win as they always have: "Bluetooth
    # Clear and Pair" says more than our "Clear the Bluetooth pairing". The platform problem is
    # specific to CHORDS, where one global name is applied to a Windows, a macOS and a VS Code
    # reading of the same keystroke.
    theirs = (nf.get("name") or "").strip()
    own = (action.get("name") or "").strip()
    is_chord = action.get("actionType") == "shortcut_alias"
    # What this entry calls itself: the name our dictionary gave it, or, for a preset with no
    # name of its own, its label -- which is already written for its category.
    ours = own or ((action.get("label") or "").strip() if is_chord else "")

    if is_chord and ours and theirs and theirs.lower() != ours.lower():
        out["name"] = ours
        out["alias"] = theirs
        # Their tooltip describes THEIR action ("Open Mission Control." under a scroll
        # command), so it travels with the name it belongs to rather than contradicting ours.
        if nf.get("tooltip"):
            out["aliasTooltip"] = nf["tooltip"]
    else:
        # Device vocabulary, unchanged: theirs leads and ours is kept as the alias.
        if theirs and own and theirs.lower() != own.lower():
            out["alias"] = own
        out["name"] = theirs or own or action["label"]
        if nf.get("tooltip"):
            out["tooltip"] = nf["tooltip"]

    if nf.get("category"):
        out["nayaflowCategory"] = nf["category"]
    if nf.get("icon"):
        out["icon"] = nf["icon"]
    return out


def get_catalog() -> dict:
    from . import shortcuts as _sc

    names = nayaflow_names()
    tabs = []
    flat: dict = {}
    for t in _tabs():
        cats = []
        for c in t.get("categories") or []:
            actions = [_describe(a, names) for a in c.get("actions") or []]
            for a in actions:
                flat.setdefault(a["code"], {k: a[k] for k in ("label", "name", "tooltip", "alias", "aliasTooltip", "icon")
                                            if k in a})
            cats.append({**c, "actions": actions})
        tabs.append({**t, "categories": cats})

    return {
        "tabs": tabs,
        # code -> {label, name, tooltip, alias} for every palette entry, so a bound key, a
        # gesture row or a search result can be described without walking the tabs.
        "names": flat,
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
