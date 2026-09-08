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
// Mouse buttons on a KEY. Confirmed on hardware 2026-09-07: a key takes the same two-word
// record a module gesture does, so these are real bindings, not app-only decoration.
// M4/M5 are what the device calls them; Back/Forward is what they do.
const MOUSE_LABEL = {
  M1: "L Click", M2: "R Click", M3: "M Click", M4: "Back", M5: "Forward",
};

// The LED system keys (&rgb_ug). Names are NayaFlow's own -- each was matched to a device record
// by flashing Naya's default profile and pairing bytes with its database, 2026-09-08.
const LED_LABEL = {
  LED_SOLID:           { main: "◼", sub: "solid" },
  LED_BREATHE:         { main: "◐", sub: "breathe" },
  LED_SWIRL:           { main: "◍", sub: "swirl" },
  LED_SPEC:            { main: "◓", sub: "spectrum" },
  LED_EFFECT:          { main: "✦", sub: "effect" },
  LED_EFFECT_ON_OFF:   { main: "⏻", sub: "lights" },
  LED_BRIGHTNESS_UP:   { main: "☀", sub: "+" },
  LED_BRIGHTNESS_DOWN: { main: "☀", sub: "−" },
  LED_SPEED_UP:        { main: "»", sub: "speed +" },
  LED_SPEED_DOWN:      { main: "«", sub: "speed −" },
  LED_COLOR_WHITE:     { main: "●", sub: "white" },
  LED_COLOR_RED:       { main: "●", sub: "red" },
  LED_COLOR_GREEN:     { main: "●", sub: "green" },
  LED_COLOR_BLUE:      { main: "●", sub: "blue" },
};

// Plain-language names for the detail panel, where a keycap only has room for a glyph.
const LED_TEXT = {
  LED_SOLID: "Lighting: Solid",
  LED_BREATHE: "Lighting: Breathe",
  LED_SWIRL: "Lighting: Swirl",
  LED_SPEC: "Lighting: Spectrum",
  LED_EFFECT: "Lighting: next effect",
  LED_EFFECT_ON_OFF: "Lighting on / off",
  LED_BRIGHTNESS_UP: "Brightness up",
  LED_BRIGHTNESS_DOWN: "Brightness down",
  LED_SPEED_UP: "Effect speed up",
  LED_SPEED_DOWN: "Effect speed down",
  LED_COLOR_WHITE: "Lighting colour: white",
  LED_COLOR_RED: "Lighting colour: red",
  LED_COLOR_GREEN: "Lighting colour: green",
  LED_COLOR_BLUE: "Lighting colour: blue",
};

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
  if (LED_TEXT[code]) return LED_TEXT[code];
  if (binding.actionType === "mouse") return MOUSE_LABEL[code] || code;
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
  if (binding.actionType === "mouse") return { main: MOUSE_LABEL[code] || code, sub: "●" };
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
  // Every LED_* code used to collapse to the string "LED", so a board carrying all fourteen
  // lighting keys showed fourteen identical caps. The device tells them apart (record type 0x09,
  // decoded in keymap_read.decode_rgb_system) and so should the keycap.
  if (LED_LABEL[code]) return LED_LABEL[code];
  if (code.startsWith("LED_")) return { main: "LED", sub: "" };
  if (code.startsWith("BT_")) return { main: "BT", sub: "" };
  return { main: code.length > 5 ? code.slice(0, 5) : code, sub: "" };
}
