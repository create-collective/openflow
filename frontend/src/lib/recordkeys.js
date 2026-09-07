// Turn a browser KeyboardEvent into the same action code the rest of the app uses.
//
// The recorder must not invent a second vocabulary. A recorded Ctrl+C has to come out as
// "LCTRL + C" -- exactly what VirtualKeyboard's resolveVirtualKey produces -- or a recorded step
// and a hand-picked step would be different things that happen to look alike.
//
// Mapping is on `event.code` (physical position) rather than `event.key` (the character
// produced), so a recording is not silently reinterpreted by the OS layout: on AZERTY,
// event.key for the Q position is "a", and recording "a" there would replay as the wrong key.

const BY_CODE = {
  Escape: "ESC", Backquote: "GRAVE", Minus: "MINUS", Equal: "EQUAL", Backspace: "BACKSPACE",
  Tab: "TAB", BracketLeft: "LEFT_BRACKET", BracketRight: "RIGHT_BRACKET", Backslash: "BACKSLASH",
  CapsLock: "CAPS", Semicolon: "SEMICOLON", Quote: "APOSTROPHE", Enter: "RETURN",
  Comma: "COMMA", Period: "DOT", Slash: "SLASH", Space: "SPACE",
  ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT",
  Insert: "INSERT", Delete: "DELETE", Home: "HOME", End: "END",
  PageUp: "PAGE_UP", PageDown: "PAGE_DOWN",
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
