// Resolve an action_code (from a key binding) into the short legend shown on the
// on-screen keycap. The glyphs come from the canonical key dictionary (keydict.js),
// so a symbol like "(" is defined in exactly one place and the board, palette, and
// virtual keyboard all agree. Falls back to the raw code so nothing renders
// blank-but-bound.

import { GLYPH, BASE_TO_SHIFT } from "./keydict";

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
  // Show the glyph for symbols/keys so the panel reads "(" not "LEFT_PARENTHESIS".
  if (GLYPH[code]) return GLYPH[code];
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
    return { main: GLYPH[parts.at(-1)] || parts.at(-1), sub: "↗" };
  }

  // The dictionary is the source of truth for glyphs. `sub` shows the shifted
  // glyph for base keys (e.g. "9" with a small "(").
  if (GLYPH[code]) {
    const shiftCode = BASE_TO_SHIFT[code];
    return { main: GLYPH[code], sub: shiftCode ? GLYPH[shiftCode] : "" };
  }

  if (/^[A-Z]$/.test(code)) return { main: code, sub: "" };
  if (/^F\d+$/.test(code)) return { main: code, sub: "" };
  if (code.startsWith("LED_")) return { main: "LED", sub: "" };
  if (code.startsWith("BT_")) return { main: "BT", sub: "" };
  return { main: code.length > 5 ? code.slice(0, 5) : code, sub: "" };
}
