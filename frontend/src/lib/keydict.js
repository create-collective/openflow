// The canonical key dictionary — the single source of truth for how an
// action_code maps to its on-screen glyph, its shifted variant, and where it sits
// on a physical keyboard. The board legend (keylabels.js), the action palette, and
// the virtual keyboard all derive from here, so a symbol is defined in exactly one
// place. `shift` is [shiftedCode, shiftedGlyph] for keys whose Shift produces a
// distinct named glyph (Shift+9 -> LEFT_PARENTHESIS "("). `u` is the key width in
// standard keyboard units (1u = a normal letter key) so the board looks real.

// mac: the Mac-mode glyph for a key whose label differs on macOS (⊞→⌘, Alt→⌥).
// The action_code is identical — LGUI is Win/Cmd, LALT is Alt/Option — so only the
// legend changes, toggled by the virtual keyboard's "Mac" checkbox.
const K = (code, glyph, shift = null, u = 1, mac = null) => ({ code, glyph, shift, u, mac });
const GAP = (u) => ({ gap: true, u });
const FMORE = { more: "fkeys", u: 1.75 }; // the "F13+" expander (wide enough for the label)
// A numpad key placed on a grid: row/col (1-based) with optional row/col spans.
const KP = (code, glyph, row, col, rspan = 1, cspan = 1) => ({ code, glyph, row, col, rspan, cspan });

// The main alpha block, as physical rows (top to bottom), for the virtual keyboard.
// Every row totals 15u; the staggered look comes from the wider first key on each
// row (Tab 1.5u, Caps 1.75u, Shift 2.25u), exactly like a real ANSI board.
export const MAIN_ROWS = [
  [K("ESC", "Esc"), GAP(0.5),
   K("F1", "F1"), K("F2", "F2"), K("F3", "F3"), K("F4", "F4"),
   K("F5", "F5"), K("F6", "F6"), K("F7", "F7"), K("F8", "F8"),
   K("F9", "F9"), K("F10", "F10"), K("F11", "F11"), K("F12", "F12"), GAP(0.5), FMORE],
  [K("GRAVE", "`", ["TILDE", "~"]), K("NUMBER_1", "1", ["EXCLAMATION", "!"]),
   K("NUMBER_2", "2", ["AT_SIGN", "@"]), K("NUMBER_3", "3", ["HASH", "#"]),
   K("NUMBER_4", "4", ["DOLLAR", "$"]), K("NUMBER_5", "5", ["PERCENT", "%"]),
   K("NUMBER_6", "6", ["CARET", "^"]), K("NUMBER_7", "7", ["AMPERSAND", "&"]),
   K("NUMBER_8", "8", ["ASTERISK", "*"]), K("NUMBER_9", "9", ["LEFT_PARENTHESIS", "("]),
   K("NUMBER_0", "0", ["RIGHT_PARENTHESIS", ")"]), K("MINUS", "-", ["UNDERSCORE", "_"]),
   K("EQUAL", "=", ["PLUS", "+"]), K("BACKSPACE", "Bksp", null, 2)],
  [K("TAB", "Tab", null, 1.5), K("Q", "Q"), K("W", "W"), K("E", "E"), K("R", "R"),
   K("T", "T"), K("Y", "Y"), K("U", "U"), K("I", "I"), K("O", "O"), K("P", "P"),
   K("LEFT_BRACKET", "[", ["LEFT_BRACE", "{"]), K("RIGHT_BRACKET", "]", ["RIGHT_BRACE", "}"]),
   K("BACKSLASH", "\\", ["PIPE", "|"], 1.5)],
  [K("CAPSLOCK", "Caps", null, 1.75), K("A", "A"), K("S", "S"), K("D", "D"), K("F", "F"),
   K("G", "G"), K("H", "H"), K("J", "J"), K("K", "K"), K("L", "L"),
   K("SEMICOLON", ";", ["COLON", ":"]), K("SINGLE_QUOTE", "'", ["DOUBLE_QUOTES", '"']),
   K("RETURN", "Enter", null, 2.25)],
  [K("LSHIFT", "Shift", null, 2.25), K("Z", "Z"), K("X", "X"), K("C", "C"), K("V", "V"),
   K("B", "B"), K("N", "N"), K("M", "M"), K("COMMA", ",", ["LESS_THAN", "<"]),
   K("PERIOD", ".", ["GREATER_THAN", ">"]), K("SLASH", "/", ["QUESTION", "?"]),
   K("RSHIFT", "Shift", null, 2.75)],
  [K("LCTRL", "Ctrl", null, 1.25, "⌃"), K("LGUI", "⊞", null, 1.25, "⌘"), K("LALT", "Alt", null, 1.25, "⌥"),
   K("SPACE", "Space", null, 6.25), K("RALT", "Alt", null, 1.25, "⌥"), K("RGUI", "⊞", null, 1.25, "⌘"),
   K("K_APP", "☰", null, 1.25), K("RCTRL", "Ctrl", null, 1.25, "⌃")],
];

// Nav cluster (its own block on the virtual keyboard).
export const NAV_ROWS = [
  [K("PRINTSCREEN", "PrtSc"), K("SCROLLLOCK", "ScrLk"), K("PAUSE_BREAK", "Pause")],
  [K("INSERT", "Ins"), K("HOME", "Home"), K("PG_UP", "PgUp")],
  [K("DELETE", "Del"), K("END", "End"), K("PG_DN", "PgDn")],
  [null, K("UP", "↑"), null],
  [K("LEFT", "←"), K("DOWN", "↓"), K("RIGHT", "→")],
];

// Numpad, on a 4-col grid. "+" and "Enter" span two rows; "0" spans two columns —
// exactly like a real numpad.
export const NUMPAD = [
  KP("KP_NUMLOCK", "Num", 1, 1), KP("KP_DIVIDE", "/", 1, 2), KP("KP_MULTIPLY", "×", 1, 3), KP("KP_MINUS", "−", 1, 4),
  KP("KP_NUMBER_7", "7", 2, 1), KP("KP_NUMBER_8", "8", 2, 2), KP("KP_NUMBER_9", "9", 2, 3), KP("KP_PLUS", "+", 2, 4, 2, 1),
  KP("KP_NUMBER_4", "4", 3, 1), KP("KP_NUMBER_5", "5", 3, 2), KP("KP_NUMBER_6", "6", 3, 3),
  KP("KP_NUMBER_1", "1", 4, 1), KP("KP_NUMBER_2", "2", 4, 2), KP("KP_NUMBER_3", "3", 4, 3), KP("KP_ENTER", "⏎", 4, 4, 2, 1),
  KP("KP_NUMBER_0", "0", 5, 1, 1, 2), KP("KP_DOT", ".", 5, 3),
];

// Extended function keys, offered via the "F13+" expander.
export const FKEYS_EXTRA = Array.from({ length: 12 }, (_, i) => `F${i + 13}`);

// Media / system keys that are mappable but not physical keys on the virtual board.
export const MEDIA = [
  K("C_MUTE", "Mute"), K("C_VOL_UP", "Vol+"), K("C_VOL_DOWN", "Vol-"),
  K("C_PLAY_PAUSE", "⏯"), K("C_NEXT", "⏭"), K("C_PREVIOUS", "⏮"),
  K("C_FAST_FORWARD", "⏩"), K("C_REWIND", "⏪"), K("C_STOP", "⏹"),
  K("C_BRIGHTNESS_INC", "Bri+"), K("C_BRIGHTNESS_DEC", "Bri-"), K("C_POWER", "Pwr"),
];

// --- derived lookups (built once) ------------------------------------------ //

// action_code -> display glyph.
export const GLYPH = {};
// base code -> its shifted code (e.g. NUMBER_9 -> LEFT_PARENTHESIS).
export const BASE_TO_SHIFT = {};

const addGlyph = (k) => {
  if (!k || !k.code) return; // skip gaps / expander markers
  GLYPH[k.code] = k.glyph;
  if (k.shift) {
    GLYPH[k.shift[0]] = k.shift[1];
    BASE_TO_SHIFT[k.code] = k.shift[0];
  }
};
for (const rows of [MAIN_ROWS, NAV_ROWS]) for (const row of rows) for (const k of row) addGlyph(k);
for (const k of NUMPAD) addGlyph(k);
for (const k of MEDIA) GLYPH[k.code] = k.glyph;
for (const f of FKEYS_EXTRA) GLYPH[f] = f;

// Non-physical-key action codes (Mouse / Connection / Empty / International /
// Recovery) so every palette tab has a board-legend glyph, not a truncated code.
const EXTRA_GLYPH = {
  TRANSPARENT: "▽", DISABLE: "✕",
  M1: "LMB", M2: "RMB", M3: "MMB", M4: "M4", M5: "M5",
  BT_DEVICE_1: "BT1", BT_DEVICE_2: "BT2", BT_DEVICE_3: "BT3", BT_DEVICE_4: "BT4",
  BT_CLEAR: "BT✕", BT_OUT: "BT", USB_DEVICE: "USB",
  MODULE_FORCE_CHARGING: "Chrg",
  NON_US_BACKSLASH: "\\", NON_US_HASH: "#",
};
for (let n = 1; n <= 9; n++) EXTRA_GLYPH[`LANG${n}`] = `Lng${n}`;
for (let n = 1; n <= 6; n++) EXTRA_GLYPH[`INT${n}`] = `Int${n}`;
Object.assign(GLYPH, EXTRA_GLYPH);

// Spellings NayaFlow uses inside its shortcut_alias codes that differ from our
// canonical codes ("LALT + ENTER" in its presets; the dictionary key is RETURN).
// Verified 2026-09-01 from a NayaFlow flash capture: NayaFlow's own encoder does
// NOT know ENTER and flashes "LALT + ENTER" as a bare Alt (HID usage 0), so the
// alias matters for the device encoder as well as for the legend.
export const CODE_ALIASES = { ENTER: "RETURN" };
for (const [alias, canonical] of Object.entries(CODE_ALIASES)) {
  if (GLYPH[canonical] !== undefined && GLYPH[alias] === undefined) GLYPH[alias] = GLYPH[canonical];
}

// The 5 held-modifier toggles under the virtual keyboard, and the action_code each
// contributes to a shortcut combo.
export const VK_MODIFIERS = [
  { id: "shift", label: "Shift", code: "LSHIFT" },
  { id: "ctrl", label: "Ctrl", code: "LCTRL" },
  { id: "win", label: "Win", code: "LGUI" },
  { id: "alt", label: "Alt", code: "LALT" },
  { id: "altgr", label: "Alt Gr", code: "RALT" },
];

// Given a base action_code and the set of held modifiers, resolve what to bind.
// - only Shift + a key with a named shifted glyph -> that glyph code (a real symbol)
// - any other modifier combination -> a shortcut_alias "LCTRL + C" style code
// - no modifiers -> the base key itself
export function resolveVirtualKey(code, mods) {
  const active = VK_MODIFIERS.filter((m) => mods[m.id]);
  if (active.length === 0) {
    return { actionCode: code, actionType: guessType(code) };
  }
  if (active.length === 1 && active[0].id === "shift" && BASE_TO_SHIFT[code]) {
    return { actionCode: BASE_TO_SHIFT[code], actionType: "key" };
  }
  const combo = [...active.map((m) => m.code), code].join(" + ");
  return { actionCode: combo, actionType: "shortcut_alias" };
}

function guessType(code) {
  if (["LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT", "LGUI", "RGUI"].includes(code))
    return "modifier";
  return "key";
}
