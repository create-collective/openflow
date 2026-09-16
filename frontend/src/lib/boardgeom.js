// The board's geometry, vendor-exact: every key, thumb, module slot and side LED bar at the
// place NayaFlow 1.25.1's own renderer puts it, from docs/reference/create-key-geometry.json
// (exported by tools/export_key_geometry.js by rendering NayaFlow's board component against its
// compiled CSS and reading the boxes back). keygeometry.json is a checked copy of that file
// (tools/check-geometry.mjs); the reference is the source of truth.
//
// Until 2026-09-16 this file was a hand-transcribed flexbox mirror of NayaFlow's Tailwind
// margins with two scale factors (1.4 px per key unit, 24.6 px per rem). Measured in the
// browser against the reference, that drifted 6.7 px per column outward (the rem scale was 10%
// too large relative to the key scale), 45 px by the inner 2u keys, and put the thumbs ~60 px
// from NayaFlow's placement. One scale over measured coordinates has no such drift by
// construction, and a parity check (tools/board_parity.js in the browser) can prove it.
//
// NayaFlow draws two boards from the same component: KEY_MAP (Bindings: keys + module slots,
// 992 x 240 css px, halves either side of a 14rem centre column) and COLOR_MAP (Colour: the
// halves 24 px further in, an 11rem centre, plus the 14 side LED bars). Both are here, in the
// app's own pixels at 16 px/rem; SCALE turns them into ours.
import GEOMETRY from "./keygeometry.json";

export { GEOMETRY };

// One scale for everything -- positions and sizes -- so proportions are the vendor's.
export const SCALE = 1.4;

// Module slot positions in the LED map: 88 lights the left module, 112 the right (a bay's LEDs
// are a 24-wide block; see flash.MODULE_LED_BLOCKS). The board keys them "left" / "right".
export const MODULE_SLOT_POS = { left: 88, right: 89 };

// Side LED bars. The GEOMETRY of the bars (16 x 28.8, seven down each outer edge) is the
// vendor's. WHICH positions sit on which edge is not taken from the vendor's picture: NayaFlow
// draws 74-80 down its left edge and 81-87 down its right, but the 2026-09-08 painting test
// (device/flash.py: "painting each band a distinct colour and looking at the keyboard") records
// 74-80 as the RIGHT edge and 81-87 as the LEFT, and hardware beats a drawing. So the left-edge
// bar slots carry 81-87 top to bottom and the right-edge ones 74-80, and the disagreement with
// NayaFlow's own Colour view stays an open check: paint 74 alone and look.
export const LEFT_LEDS = [81, 82, 83, 84, 85, 86, 87];
export const RIGHT_LEDS = [74, 75, 76, 77, 78, 79, 80];

const KEY_BY_POS = Object.fromEntries(GEOMETRY.keys.map((k) => [k.position, k]));

function box(p, w, h) {
  return { x: p.x * SCALE, y: p.y * SCALE, w: w * SCALE, h: h * SCALE };
}

// Everything the board needs for one mode, in our pixels. `keys` includes the thumbs and the 2u
// inner keys: on the vendor's board they are simply keys at positions, not a separate cluster.
export function boardLayout(mode) {
  const prop = mode === "color" ? "colorMap" : "keyMap";
  const board = mode === "color" ? GEOMETRY.boards.COLOR_MAP : GEOMETRY.boards.KEY_MAP;
  const keys = GEOMETRY.keys.map((k) => ({ pos: k.position, label: k.label, half: k.half,
                                           role: k.role, ...box(k[prop], k.width, k.height) }));
  let leds = [];
  if (mode === "color") {
    const bars = (side) => GEOMETRY.leds.filter((l) => l.side === side)
      .sort((a, b) => a.colorMap.y - b.colorMap.y);
    leds = [
      ...bars("left-outer").map((l, i) => ({ pos: LEFT_LEDS[i], side: "left", ...box(l.colorMap, l.width, l.height) })),
      ...bars("right-outer").map((l, i) => ({ pos: RIGHT_LEDS[i], side: "right", ...box(l.colorMap, l.width, l.height) })),
    ];
  }
  // The pocket between the halves: from the left 2u key's inner edge to the right 2u key's,
  // and from the top down to the thumb row. NayaFlow puts its two 48 px slot icons in it;
  // OpenFlow puts its own module pocket (larger round bays, the docked module's picture) in
  // the same box, so the halves stay exactly where the vendor's are.
  const lh1 = KEY_BY_POS[7][prop], rh1 = KEY_BY_POS[8][prop];
  const thumbTop = Math.min(...[37, 53, 67, 38, 54, 68].map((p) => KEY_BY_POS[p][prop].y));
  const pocket = { x: (lh1.x + KEY_BY_POS[7].width) * SCALE, y: 0,
                   w: (rh1.x - lh1.x - KEY_BY_POS[7].width) * SCALE, h: thumbTop * SCALE };
  const vendorSlots = GEOMETRY.moduleSlots.map((m) => ({ side: m.side, pos: MODULE_SLOT_POS[m.side],
                                                         ...box(m[prop], m.width, m.height) }));
  const height = Math.max(...keys.map((k) => k.y + k.h), ...leds.map((l) => l.y + l.h));
  return { width: board.width * SCALE, height: Math.ceil(height), keys, leds, pocket, vendorSlots };
}
