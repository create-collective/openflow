// Turn a browser KeyboardEvent into the same action code the rest of the app uses.
//
// The recorder must not invent a second vocabulary. A recorded Ctrl+C has to come out as
// "LCTRL + C" -- exactly what VirtualKeyboard's resolveVirtualKey produces -- or a recorded step
// and a hand-picked step would be different things that happen to look alike.
//
// Mapping is on `event.code` (physical position) rather than `event.key` (the character
// produced), so a recording is not silently reinterpreted by the OS layout: on AZERTY,
// event.key for the Q position is "a", and recording "a" there would replay as the wrong key.

// Every value here must be a code the palette and the device encoder already know
// (keymap_read.PAGE7 names). Five of them were not -- CAPS, APOSTROPHE, DOT, PAGE_UP and
// PAGE_DOWN were the recorder's own spellings -- so a recorded Caps Lock, quote, period or
// Page Up/Down was refused at flash time as an unknown key. Found by the 2026-09-09 coverage
// probe; the backend also accepts PAGE_UP/PAGE_DOWN as aliases because NayaFlow's recorder
// emits them, but the fix is to not invent spellings in the first place.
const BY_CODE = {
  Escape: "ESC", Backquote: "GRAVE", Minus: "MINUS", Equal: "EQUAL", Backspace: "BACKSPACE",
  Tab: "TAB", BracketLeft: "LEFT_BRACKET", BracketRight: "RIGHT_BRACKET", Backslash: "BACKSLASH",
  CapsLock: "CAPSLOCK", Semicolon: "SEMICOLON", Quote: "SINGLE_QUOTE", Enter: "RETURN",
  Comma: "COMMA", Period: "PERIOD", Slash: "SLASH", Space: "SPACE",
  ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT",
  Insert: "INSERT", Delete: "DELETE", Home: "HOME", End: "END",
  PageUp: "PG_UP", PageDown: "PG_DN", PrintScreen: "PRINTSCREEN", ScrollLock: "SCROLLLOCK",
  Pause: "PAUSE_BREAK", ContextMenu: "K_APP", NumLock: "KP_NUMLOCK", NumpadEnter: "KP_ENTER",
  NumpadDecimal: "KP_DOT", NumpadAdd: "KP_PLUS", NumpadSubtract: "KP_MINUS",
  NumpadMultiply: "KP_MULTIPLY", NumpadDivide: "KP_DIVIDE",
};

const MODIFIER_CODES = new Set([
  "ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight",
  "AltLeft", "AltRight", "MetaLeft", "MetaRight", "CapsLock",
]);

function baseCode(e) {
  const c = e.code || "";
  if (BY_CODE[c]) return BY_CODE[c];
  if (/^Key[A-Z]$/.test(c)) return c.slice(3);              // KeyA -> A
  if (/^Digit[0-9]$/.test(c)) return `NUMBER_${c.slice(5)}`; // Digit1 -> NUMBER_1
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(c)) return c;          // F1..F24
  if (/^Numpad[0-9]$/.test(c)) return `KP_NUMBER_${c.slice(6)}`;
  return null;
}

/**
 * A keydown -> {actionCode, label}, or null when the event is only a modifier being pressed
 * (we wait for the key it modifies, so Ctrl+C records as one step rather than two).
 */
export function chordFromEvent(e) {
  if (MODIFIER_CODES.has(e.code)) return null;
  const base = baseCode(e);
  if (!base) return null;

  const mods = [];
  if (e.ctrlKey) mods.push("LCTRL");
  if (e.shiftKey) mods.push("LSHIFT");
  if (e.altKey) mods.push("LALT");
  if (e.metaKey) mods.push("LGUI");

  if (mods.length === 0) {
    return { actionCode: base, actionType: "key", label: base };
  }
  const code = [...mods, base].join(" + ");
  return { actionCode: code, actionType: "shortcut_alias", label: code };
}
