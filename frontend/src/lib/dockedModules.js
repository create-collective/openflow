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

// Backend type names -> the keys KeymapBoard draws with. Anything absent here (Float, or an
// address we have not mapped yet) resolves to null, so an unidentified module leaves the bay
// empty rather than guessing at a picture.
const TYPE_TO_ART = { Track: "track", Touch: "touch", Tune: "tune" };

/**
 * Ask the board which module is in which bay.
 * Returns { left, right } with an art key or null per bay.
 */
export async function readDockedModules(api) {
  const status = await api.status();
  const bays = { left: null, right: null };
  for (const half of status.halves || []) {
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
