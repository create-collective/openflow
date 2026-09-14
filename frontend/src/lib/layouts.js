// Cosmetic virtual-keyboard layouts. Picking one only changes how the on-screen keyboard is
// LABELLED and arranged -- it never changes what a key binds by position. A key still binds the
// keycode its LABEL names: the "A" key binds A wherever a layout happens to draw it (bind-by-label,
// the owner's decision 2026-09-13). The layout is a presentation preference, not a device setting
// and not a claim about the user's OS layout.
//
// Each layout is a partial map: QWERTY position code -> { g: baseGlyph, s: shiftGlyph? }. Positions
// absent from the map keep their keydict.js default. VirtualKeyboard resolves the glyph to a
// keycode via CODE_FOR_GLYPH; a glyph with no US keycode (an AZERTY accent, say) has nothing to
// bind, so that key keeps its own position code and the glyph is display-only. Rows covered:
// number row, three letter rows, main punctuation -- F-keys, nav, numpad and modifiers are
// layout-invariant. Letter data is Wikipedia-confirmed; punctuation is the standard OS map. FR /
// DE / standard-Colemak variants ship first (see docs / the research note for BE, Colemak-DH).

const AZERTY = {
  GRAVE: { g: "²" },
  NUMBER_1: { g: "&", s: "1" }, NUMBER_2: { g: "é", s: "2" }, NUMBER_3: { g: '"', s: "3" },
  NUMBER_4: { g: "'", s: "4" }, NUMBER_5: { g: "(", s: "5" }, NUMBER_6: { g: "-", s: "6" },
  NUMBER_7: { g: "è", s: "7" }, NUMBER_8: { g: "_", s: "8" }, NUMBER_9: { g: "ç", s: "9" },
  NUMBER_0: { g: "à", s: "0" }, MINUS: { g: ")", s: "°" }, EQUAL: { g: "=", s: "+" },
  Q: { g: "A" }, W: { g: "Z" },
  LEFT_BRACKET: { g: "^", s: "¨" }, RIGHT_BRACKET: { g: "$", s: "£" },
  BACKSLASH: { g: "*", s: "µ" },
  A: { g: "Q" }, SEMICOLON: { g: "M" }, SINGLE_QUOTE: { g: "ù", s: "%" },
  Z: { g: "W" }, M: { g: ",", s: "?" }, COMMA: { g: ";", s: "." },
  PERIOD: { g: ":", s: "/" }, SLASH: { g: "!", s: "§" },
};

const QWERTZ = {
  GRAVE: { g: "^", s: "°" },
  NUMBER_2: { g: "2", s: '"' }, NUMBER_3: { g: "3", s: "§" }, NUMBER_6: { g: "6", s: "&" },
  NUMBER_7: { g: "7", s: "/" }, NUMBER_8: { g: "8", s: "(" }, NUMBER_9: { g: "9", s: ")" },
  NUMBER_0: { g: "0", s: "=" }, MINUS: { g: "ß", s: "?" }, EQUAL: { g: "´", s: "`" },
  Y: { g: "Z" },
  LEFT_BRACKET: { g: "ü", s: "Ü" }, RIGHT_BRACKET: { g: "+", s: "*" },
  BACKSLASH: { g: "#", s: "'" },
  SEMICOLON: { g: "ö", s: "Ö" }, SINGLE_QUOTE: { g: "ä", s: "Ä" },
  Z: { g: "Y" }, COMMA: { g: ",", s: ";" }, PERIOD: { g: ".", s: ":" }, SLASH: { g: "-", s: "_" },
};

const DVORAK = {
  MINUS: { g: "[", s: "{" }, EQUAL: { g: "]", s: "}" },
  Q: { g: "'", s: '"' }, W: { g: ",", s: "<" }, E: { g: ".", s: ">" },
  R: { g: "P" }, T: { g: "Y" }, Y: { g: "F" }, U: { g: "G" }, I: { g: "C" }, O: { g: "R" }, P: { g: "L" },
  LEFT_BRACKET: { g: "/", s: "?" }, RIGHT_BRACKET: { g: "=", s: "+" },
  S: { g: "O" }, D: { g: "E" }, F: { g: "U" }, G: { g: "I" }, H: { g: "D" }, J: { g: "H" },
  K: { g: "T" }, L: { g: "N" }, SEMICOLON: { g: "S" }, SINGLE_QUOTE: { g: "-", s: "_" },
  Z: { g: ";", s: ":" }, X: { g: "Q" }, C: { g: "J" }, V: { g: "K" }, B: { g: "X" }, N: { g: "B" },
  COMMA: { g: "W" }, PERIOD: { g: "V" }, SLASH: { g: "Z" },
};

const COLEMAK = {
  E: { g: "F" }, R: { g: "P" }, T: { g: "G" }, Y: { g: "J" }, U: { g: "L" }, I: { g: "U" },
  O: { g: "Y" }, P: { g: ";", s: ":" },
  S: { g: "R" }, D: { g: "S" }, F: { g: "T" }, G: { g: "D" }, J: { g: "N" }, K: { g: "E" }, L: { g: "I" },
  SEMICOLON: { g: "O" }, N: { g: "K" },
};

export const LAYOUTS = {
  qwerty: { label: "QWERTY", overrides: {} },
  azerty: { label: "AZERTY (FR)", overrides: AZERTY },
  qwertz: { label: "QWERTZ (DE)", overrides: QWERTZ },
  dvorak: { label: "Dvorak", overrides: DVORAK },
  colemak: { label: "Colemak", overrides: COLEMAK },
};

export const LAYOUT_IDS = Object.keys(LAYOUTS);
