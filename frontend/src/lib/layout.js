// Naya Create physical layout, derived from the recovered `Zdt` map in the
// NayaFlow renderer: position_id -> physical label [L|R][col A-H][row 1-5].
//   col A-G = finger columns (A = outer/pinky), H = thumb cluster; row 1 = top.
// We turn each label into an (x, y) on a split columnar board with per-column
// stagger, so the on-screen key at a position_id is the real physical key.

// position_id -> label (0..73 keyswitches). Verbatim from index-mihUmo_8.js (Zdt).
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

// Per-column vertical stagger (in key units) approximating the Create's columnar
// ergonomics — middle columns raised, pinky/index dropped. Tuned to the reference.
const COL_STAGGER = { A: 0.55, B: 0.35, C: 0.15, D: 0.0, E: -0.12, F: 0.12, G: 0.32, H: 1.7 };
// Finger-column order, left half left->right; right half mirrors.
const LEFT_COLS = ["A", "B", "C", "D", "E", "F", "G"];
const RIGHT_COLS = ["G", "F", "E", "D", "C", "B", "A"];

const UNIT = 3.0;       // rem per key cell
const GAP = 0.28;       // rem between keys
const HALF_GAP = 3.6;   // rem gap between the two halves (module zone)

function parseLabel(label) {
  return { half: label[0], col: label[1], row: parseInt(label[2], 10) };
}

// Build [{positionId, label, half, col, row, x, y}] with rem coordinates.
export function buildLayout() {
  const cell = UNIT + GAP;
  const keys = [];
  let leftWidth = LEFT_COLS.length * cell;

  for (const [pid, label] of Object.entries(POS_LABEL)) {
    const { half, col, row } = parseLabel(label);
    const positionId = Number(pid);
    let x, y;
    const stag = (COL_STAGGER[col] ?? 0) * cell;

    if (col === "H") {
      // Thumb clusters: a clean arc below each half, angled toward the center.
      const idx = row - 1; // LH1..LH4 -> 0..3
      const step = cell * 0.98;
      const ty = 4.35 * cell + Math.abs(1.5 - idx) * cell * 0.14; // slight arc
      if (half === "L") {
        // ends just short of the center gap
        x = leftWidth - (4 - idx) * step + step * 0.5;
      } else {
        x = leftWidth + HALF_GAP - step * 0.5 + idx * step;
      }
      y = ty;
    } else {
      if (half === "L") {
        const ci = LEFT_COLS.indexOf(col);
        x = ci * cell;
      } else {
        const ci = RIGHT_COLS.indexOf(col);
        x = leftWidth + HALF_GAP + ci * cell;
      }
      y = (row - 1) * cell + stag;
    }
    keys.push({ positionId, label, half, col, row, x, y });
  }

  // Normalize so the minimum x/y is 0.
  const minY = Math.min(...keys.map((k) => k.y));
  const minX = Math.min(...keys.map((k) => k.x));
  keys.forEach((k) => {
    k.y -= minY;
    k.x -= minX;
  });
  const maxX = Math.max(...keys.map((k) => k.x)) + UNIT;
  const maxY = Math.max(...keys.map((k) => k.y)) + UNIT;

  return { keys, width: maxX, height: maxY, unit: UNIT };
}

// Non-keyswitch elements for the color/LED view (module slots + LED zones).
// From the renderer: 88 = left module slot, 89 = right module slot.
export const MODULE_SLOTS = [88, 89];
