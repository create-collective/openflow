// Naya Create physical layout for the on-screen board.
//
// position_id -> physical label from the recovered `Zdt` map; visual placement is
// explicit (unit = one 1u key), tuned against the NayaFlow screenshots
// (uipolish2 / reallifelook). RETURN (7) / BACKSPACE (8) are 2u inner keys; the
// thumb cluster (H2/H3/H4) is a separate arc BELOW the main block so it never
// collides with the wide bottom-row Space; modules sit spread in the center gap;
// the 7+7 side LEDs (positions 74-87) render in color mode.

export const POS_LABEL = {
  0: "LA1", 1: "LB1", 2: "LC1", 3: "LD1", 4: "LE1", 5: "LF1", 6: "LG1", 7: "LH1",
  8: "RH1", 9: "RG1", 10: "RF1", 11: "RE1", 12: "RD1", 13: "RC1", 14: "RB1", 15: "RA1",
  16: "LA2", 17: "LB2", 18: "LC2", 19: "LD2", 20: "LE2", 21: "LF2", 22: "LG2",
  23: "RG2", 24: "RF2", 25: "RE2", 26: "RD2", 27: "RC2", 28: "RB2", 29: "RA2",
  30: "LA3", 31: "LB3", 32: "LC3", 33: "LD3", 34: "LE3", 35: "LF3", 36: "LG3",
  39: "RG3", 40: "RF3", 41: "RE3", 42: "RD3", 43: "RC3", 44: "RB3", 45: "RA3",
  46: "LA4", 47: "LB4", 48: "LC4", 49: "LD4", 50: "LE4", 51: "LF4", 52: "LG4",
  55: "RG4", 56: "RF4", 57: "RE4", 58: "RD4", 59: "RC4", 60: "RB4", 61: "RA4",
  62: "LA5", 63: "LB5", 64: "LC5", 65: "LD5", 66: "LE5",
  37: "LH2", 53: "LH3", 67: "LH4", 68: "RH4", 54: "RH3", 38: "RH2",
  69: "RE5", 70: "RD5", 71: "RC5", 72: "RB5", 73: "RA5",
};

const COL_X = { A: 0, B: 1, C: 2, D: 3, E: 4, F: 5, G: 6 };
const COL_STAG = { A: 0.5, B: 0.32, C: 0.12, D: 0.0, E: 0.12, F: 0.32, G: 0.55 };

const FINGER_W = 8;      // finger block incl. the 2u inner column (x 0..8)
const CENTER_GAP = 6;    // open middle (module zone)
const TOTAL = FINGER_W * 2 + CENTER_GAP;

// LED side zones (color mode): 7 bars per outer edge.
const LEFT_LEDS = [81, 82, 83, 84, 85, 86, 87];   // outer-left
const RIGHT_LEDS = [74, 75, 76, 77, 78, 79, 80];  // outer-right

function geomFor(col, row) {
  if (col !== "H") {
    const x = COL_X[col];
    const y = row - 1 + COL_STAG[col];
    // Wide bottom-row space: nudge down so it clears the row-4 keys (V/B, N/M).
    if (col === "E" && row === 5) return { x, y: y + 0.32, w: 2.2, h: 1 };
    return { x, y, w: 1, h: 1 };
  }
  if (row === 1) return { x: 7, y: 0.55, w: 1, h: 2 };            // 2u inner (Enter/Bksp)
  if (row === 2) return { x: 6.9, y: 5.7, w: 1.4, h: 1, rot: 14 }; // thumb space
  if (row === 3) return { x: 8.4, y: 6.15, w: 1.1, h: 1, rot: 14 };
  return { x: 9.5, y: 6.6, w: 1.1, h: 1, rot: 14 };               // thumb hold
}

function parseLabel(label) {
  return { half: label[0], col: label[1], row: parseInt(label[2], 10) };
}

export function buildLayout() {
  const keys = [];
  for (const [pid, label] of Object.entries(POS_LABEL)) {
    const { half, col, row } = parseLabel(label);
    const g = geomFor(col, row);
    const rot = g.rot || 0;
    const x = half === "L" ? g.x : TOTAL - (g.x + g.w);
    keys.push({
      positionId: Number(pid), label, half, col, row,
      x, y: g.y, w: g.w, h: g.h, rot: half === "R" ? -rot : rot,
    });
  }

  // LED side bars (color mode), aligned to the outer key column (Esc..Hold /
  // =..Hold) so they line up with the keyboard like the reference (uipolish2).
  const ledZones = [];
  const barW = 0.42, barH = 0.62, barGap = 0.72, barTop = 0.55;
  LEFT_LEDS.forEach((pid, i) =>
    ledZones.push({ positionId: pid, x: -1.15, y: barTop + i * barGap, w: barW, h: barH })
  );
  RIGHT_LEDS.forEach((pid, i) =>
    ledZones.push({ positionId: pid, x: TOTAL + 0.75, y: barTop + i * barGap, w: barW, h: barH })
  );

  // Modules spread toward each half, leaving the center open.
  const modules = [
    { id: "left", positionId: 88, x: FINGER_W + 0.4, y: 2.0, w: 1.8, h: 1.8 },
    { id: "right", positionId: 89, x: TOTAL - FINGER_W - 2.2, y: 2.0, w: 1.8, h: 1.8 },
  ];

  // Normalize so min x/y is 0 (LED bars sit at negative x).
  const all = [...keys, ...ledZones, ...modules];
  const minX = Math.min(...all.map((k) => k.x));
  const minY = Math.min(...all.map((k) => k.y));
  for (const k of all) { k.x -= minX; k.y -= minY; }

  const width = Math.max(...all.map((k) => k.x + k.w));
  const height = Math.max(...all.map((k) => k.y + k.h));
  return { keys, ledZones, modules, width, height, unit: 1 };
}
