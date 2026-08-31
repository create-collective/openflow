// Naya Create physical layout for the on-screen board.
//
// position_id -> physical label comes from the recovered `Zdt` map, but the
// VISUAL placement is not the naive matrix: e.g. RETURN (pos 7, label LH1) and
// BACKSPACE (pos 8, RH1) render as 2u vertical keys at each half's inner-top,
// while the thumb clusters are only H2/H3/H4. We encode the real geometry
// explicitly (unit = one 1u key), tuned against the NayaFlow screenshots.

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

// Finger-column x (outer A -> inner G), and per-column vertical stagger (bowl,
// middle finger highest). Coordinates are in key units, x growing toward center.
const COL_X = { A: 0, B: 1, C: 2, D: 3, E: 4, F: 5, G: 6 };
const COL_STAG = { A: 0.5, B: 0.32, C: 0.12, D: 0.0, E: 0.12, F: 0.32, G: 0.55 };

const GAP = 4.2; // center gap (module zone) in key units

// Left-half geometry for a (col,row), x growing toward the inner edge.
function geomFor(col, row) {
  if (col !== "H") {
    const x = COL_X[col];
    const y = row - 1 + COL_STAG[col];
    // Wide bottom-row space at column E, row 5.
    if (col === "E" && row === 5) return { x, y, w: 2.5, h: 1 };
    return { x, y, w: 1, h: 1 };
  }
  // Thumb column H (row = 1..4).
  if (row === 1) return { x: 7, y: 0.55, w: 1, h: 2 }; // 2u inner key (Enter/Bksp)
  // Thumb cluster arc (H2/H3/H4), angled inward.
  if (row === 2) return { x: 6.2, y: 5.05, w: 1.5, h: 1, rot: 16 }; // wide thumb (space)
  if (row === 3) return { x: 7.85, y: 5.5, w: 1.1, h: 1, rot: 16 };
  return { x: 9.0, y: 6.0, w: 1.1, h: 1, rot: 16 }; // H4 (hold)
}

function parseLabel(label) {
  return { half: label[0], col: label[1], row: parseInt(label[2], 10) };
}

export function buildLayout() {
  // Left half extent, to compute the mirror axis for the right half.
  let leftW = 0;
  for (const label of Object.values(POS_LABEL)) {
    const { half, col, row } = parseLabel(label);
    if (half !== "L") continue;
    const g = geomFor(col, row);
    leftW = Math.max(leftW, g.x + g.w);
  }
  const total = leftW * 2 + GAP;

  const keys = [];
  for (const [pid, label] of Object.entries(POS_LABEL)) {
    const { half, col, row } = parseLabel(label);
    const g = geomFor(col, row);
    const rot = g.rot || 0;
    let x;
    if (half === "L") x = g.x;
    else x = total - (g.x + g.w); // mirror
    keys.push({
      positionId: Number(pid),
      label,
      half,
      col,
      row,
      x,
      y: g.y,
      w: g.w,
      h: g.h,
      rot: half === "R" ? -rot : rot,
    });
  }

  const height = Math.max(...keys.map((k) => k.y + k.h));
  // Module slots in the center gap (clickable -> Modules page).
  const centerX = total / 2;
  const modules = [
    { id: "left", positionId: 88, x: centerX - 1.75, y: 1.1, w: 1.5, h: 1.5 },
    { id: "right", positionId: 89, x: centerX + 0.25, y: 1.1, w: 1.5, h: 1.5 },
  ];

  return { keys, modules, width: total, height, unit: 1 };
}
