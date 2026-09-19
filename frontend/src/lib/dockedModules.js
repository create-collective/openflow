// What is physically plugged into each half, according to the keyboard itself.
//
// The virtual Create used to show whatever had last been dragged onto it by hand, kept in
// localStorage -- so it happily claimed a Track in both bays while a Tune was docked on the
// right. Reading the keymap never corrected it, because the keymap does not say what the
// hardware is.
//
// The dock-bus address does. It encodes the module type AND the half it is docked on
// (bit 0 = side: 0 left, 1 right), which the backend resolves into `type` and `docked`
// on /api/status. That is measured, not inferred, so it is what the board should draw.
//
// Since 2026-09-16 that is also the ONLY source. The backend keeps the last status it read
// (db/device_state, served by /api/status/last without touching the port), so the board
// paints its bays from that on load and there is no browser-side copy to drift: a fresh
// browser, another machine, a cleared cache all show what the keyboard last reported. A half
// that was disconnected at the last read leaves its bay empty rather than guessing.

// Backend type names -> the keys KeymapBoard draws with. Anything absent here (Float, or an
// address we have not mapped yet) resolves to null, so an unidentified module leaves the bay
// empty rather than guessing at a picture.
const TYPE_TO_ART = { Track: "track", Touch: "touch", Tune: "tune" };

/**
 * { left, right } with an art key or null per bay, from a list of half snapshots.
 *
 * Returns NULL when there are no halves to reason about, which is a different answer from
 * "both bays are empty" and has to stay distinguishable: the caller leaves the board alone
 * when told nothing, and repaints when told something. An EMPTY array is being told
 * something -- no keyboard on USB means no modules docked.
 */
export function baysFromHalves(halves) {
  if (!halves) return null;
  const bays = { left: null, right: null };
  for (const half of halves) {
    const module = half.module;
    if (!module) continue;
    // Prefer the side the address reports over which port answered. They agree on healthy
    // hardware; when they disagree the address is the one that actually measured it.
    const bay = module.docked || half.side;
    if (bay === "left" || bay === "right") {
      bays[bay] = TYPE_TO_ART[module.type] || null;
    }
  }
  return bays;
}

/**
 * Ask the board which module is in which bay. Opens the port.
 * Returns { left, right } with an art key or null per bay.
 */
export async function readDockedModules(api) {
  const status = await api.status();
  return baysFromHalves(status.halves);
}

/**
 * What the board reported the LAST time it was read, from the backend's persisted status.
 * Touches no hardware; { left: null, right: null } when nothing has ever been read.
 */
export async function lastDockedModules(api) {
  const last = await api.statusLast();
  return baysFromHalves(last?.halves);
}
