// NayaFlow's exact physical board structure: columns (DOM order = screen L->R),
// per-column top-margin stagger + per-key wrapper offsets, thumbs, LED zones.
// Values are the verbatim Tailwind rem tokens from their renderer. Rendered as a
// flexbox mirror of their layout, with our own (preferred) module zone in the
// center. See docs/asset-provenance.md.

export const LEFT_COLS = [
  { mt: 1.5, mr: 0.5, keys: [0, 16, 30, 46, 62] },  // A (outer pinky)
  { mt: 1.0, mr: 0.6, keys: [1, 17, 31, 47, 63] },  // B
  { mt: 0.5, mr: 0.5, keys: [2, 18, 32, 48, 64] },  // C
  { mt: 0.2, mr: 0.5, keys: [3, 19, 33, 49, 65] },  // D
  { mt: 0.0, mr: 0.5, keys: [4, 20, 34, 50, 66] },  // E
  { mt: 0.0, mr: 0.5, keys: [5, 21, 35, 51] },      // F
  { mt: 0.15, mr: 0.5, keys: [6, 22, 36, 52] },     // G
  { mt: 0.3, mr: 0.0, keys: [7] },                  // H (2u Enter)
];

export const RIGHT_COLS = [
  { mt: 0.3, ml: 0.0, keys: [8] },                  // H' (2u Bksp)
  { mt: 0.15, ml: 0.5, keys: [9, 23, 39, 55] },     // G'
  { mt: 0.0, ml: 0.5, keys: [10, 24, 40, 56] },     // F'
  { mt: 0.0, ml: 0.5, keys: [11, 25, 41, 57, 69] }, // E'
  { mt: 0.2, ml: 0.5, keys: [12, 26, 42, 58, 70] }, // D'
  { mt: 0.5, ml: 0.5, keys: [13, 27, 43, 59, 71] }, // C'
  { mt: 1.0, ml: 0.6, keys: [14, 28, 44, 60, 72] }, // B'
  { mt: 1.5, ml: 0.5, keys: [15, 29, 45, 61, 73] }, // A' (outer pinky)
];

// Per-key protrusion wrappers (rem offsets applied to the individual key).
export const KEY_WRAPPERS = {
  50: { pt: 0.1, ml: 2.6 },
  66: { pt: 0.1, ml: 4.0, dx: 2.6 },  // Space: reach inner edge to line up with Enter
  36: { mr: 0.2 },
  39: { ml: 2.6 },
  57: { pt: 0.1, ml: 2.6 },
  69: { pt: 0.1, mr: 4.0, dx: -2.6 }, // Space: reach inner edge to line up with Bksp
};

export const LEFT_THUMBS = [37, 53, 67];
export const RIGHT_THUMBS = [68, 54, 38];
export const LEFT_LEDS = [81, 82, 83, 84, 85, 86, 87];
export const RIGHT_LEDS = [74, 75, 76, 77, 78, 79, 80];

// Sizing: px per viewBox unit (keys) and px per rem (margins), tuned to preserve
// NayaFlow's proportions while fitting our layout area.
export const KEY_UNIT = 0.82;
export const REM = 14.4;
