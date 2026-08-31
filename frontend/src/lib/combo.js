// Format a shortcut combo (e.g. "LGUI + LSHIFT + Z") into a compact glyph string
// for the palette button; the full human description shows as the tooltip.

const TOKEN = {
  LGUI: "⌘", RGUI: "⌘", // ⌘
  LCTRL: "⌃", RCTRL: "⌃", // ⌃
  LSHIFT: "⇧", RSHIFT: "⇧", // ⇧
  LALT: "⌥", RALT: "⌥", // ⌥
  "[LALT]": "⌥",
  SPACE: "␣", TAB: "⇥", RETURN: "⏎", ENTER: "⏎",
  BACKSPACE: "⌫", DELETE: "⌦", ESC: "Esc",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→",
  PG_UP: "PgUp", PG_DN: "PgDn", HOME: "Home", END: "End",
  GRAVE: "`", COMMA: ",", CLICK: "Click", C_POWER: "⏻",
};

function tok(t) {
  if (t in TOKEN) return TOKEN[t];
  if (/^NUMBER_(\d)$/.test(t)) return t.slice(-1);
  if (/^F\d+$/.test(t)) return t;
  return t;
}

export function formatCombo(code) {
  if (!code) return "";
  return code.split(" + ").map(tok).join(" ");
}
