// Resolve an action_code (from a key binding) into the short legend shown on the
// on-screen keycap. Mirrors how NayaFlow labels keys: letters/numbers show the
// glyph, modifiers/control keys show a short name, layer keys show "Hold"/"To"
// etc. Falls back to the raw code so nothing renders blank-but-bound.

const NUMBER_GLYPH = {
  NUMBER_0: "0", NUMBER_1: "1", NUMBER_2: "2", NUMBER_3: "3", NUMBER_4: "4",
  NUMBER_5: "5", NUMBER_6: "6", NUMBER_7: "7", NUMBER_8: "8", NUMBER_9: "9",
};
const NUMBER_SHIFT = {
  NUMBER_1: "!", NUMBER_2: "@", NUMBER_3: "#", NUMBER_4: "$", NUMBER_5: "%",
  NUMBER_6: "^", NUMBER_7: "&", NUMBER_8: "*", NUMBER_9: "(", NUMBER_0: ")",
};
const SYMBOL_GLYPH = {
  GRAVE: "`", MINUS: "-", EQUAL: "=", LEFT_BRACKET: "[", RIGHT_BRACKET: "]",
  BACKSLASH: "\\", SEMICOLON: ";", SINGLE_QUOTE: "'", COMMA: ",", PERIOD: ".",
  SLASH: "/",
};
const SYMBOL_SHIFT = {
  GRAVE: "~", MINUS: "_", EQUAL: "+", LEFT_BRACKET: "{", RIGHT_BRACKET: "}",
  BACKSLASH: "|", SEMICOLON: ":", SINGLE_QUOTE: '"', COMMA: "<", PERIOD: ">",
  SLASH: "?",
};
const NAMED = {
  ESC: "Esc", TAB: "Tab", RETURN: "Enter", BACKSPACE: "Bksp", DELETE: "Del",
  SPACE: "Space", CAPSLOCK: "Caps", INSERT: "Ins", PRINTSCREEN: "PrtSc",
  HOME: "Home", END: "End", PG_UP: "PgUp", PG_DN: "PgDn",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→",
  LCTRL: "Ctrl", RCTRL: "Ctrl", LSHIFT: "Shift", RSHIFT: "Shift",
  LALT: "Alt", RALT: "Alt", LGUI: "⌘", RGUI: "⌘",
  C_MUTE: "Mute", C_VOL_UP: "Vol+", C_VOL_DOWN: "Vol-", C_PLAY_PAUSE: "⏯",
  C_NEXT: "⏭", C_PREVIOUS: "⏮", DISABLE: "",
};

// Layer-switch action_code prefixes -> a short type tag.
const LAYER_KINDS = [
  ["MO_LAYER_", "MO"], ["TOGGLE_LAYER_", "TOG"],
  ["TO_LAYER_", "TO"], ["STICKY_LAYER_", "SL"],
];

function layerLegend(code, layerMap) {
  for (const [prefix, type] of LAYER_KINDS) {
    if (code.startsWith(prefix)) {
      const id = code.slice(prefix.length);
      const num = layerMap && layerMap[id] != null ? layerMap[id] : "?";
      return { layer: { type, num } };
    }
  }
  return null;
}

// Human label for the selected-key panel (resolves layer ids to "Hold Layer N").
const LAYER_TEXT = { MO: "Hold Layer", TOG: "Toggle Layer", TO: "Force Layer", SL: "Sticky Layer" };
export function actionText(binding, layerMap) {
  if (!binding || !binding.actionCode) return "Unassigned";
  const code = binding.actionCode;
  for (const [prefix, type] of LAYER_KINDS) {
    if (code.startsWith(prefix)) {
      const num = layerMap && layerMap[code.slice(prefix.length)];
      return `${LAYER_TEXT[type]} ${num != null ? num : "?"}`;
    }
  }
  if (binding.actionType === "macro") return "Macro";
  return code;
}

export function keyLegend(binding, layerMap) {
  if (!binding || !binding.actionCode) return { main: "", sub: "" };
  const code = binding.actionCode;

  const layer = layerLegend(code, layerMap);
  if (layer) return layer;

  if (binding.actionType === "macro") return { main: "Macro", sub: "⚡" };
  if (binding.actionType === "shortcut_alias" || code.includes(" + ")) {
    const parts = code.split(" + ");
    return { main: NAMED[parts.at(-1)] || parts.at(-1), sub: "↗" };
  }

  if (/^[A-Z]$/.test(code)) return { main: code, sub: "" };
  if (code in NUMBER_GLYPH) return { main: NUMBER_GLYPH[code], sub: NUMBER_SHIFT[code] || "" };
  if (code in SYMBOL_GLYPH) return { main: SYMBOL_GLYPH[code], sub: SYMBOL_SHIFT[code] || "" };
  if (code in NAMED) return { main: NAMED[code], sub: "" };
  if (/^F\d+$/.test(code)) return { main: code, sub: "" };
  if (code.startsWith("KP_NUMBER_")) return { main: code.slice(-1), sub: "" };
  if (code.startsWith("LED_")) return { main: "LED", sub: "" };
  if (code.startsWith("BT_")) return { main: "BT", sub: "" };

  // shortcut_alias combos ("LCTRL + C") -> show the last key
  if (code.includes(" + ")) {
    const parts = code.split(" + ");
    return { main: (NAMED[parts.at(-1)] || parts.at(-1)), sub: "…" };
  }
  return { main: code.length > 5 ? code.slice(0, 5) : code, sub: "" };
}
