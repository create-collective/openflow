// Plain-English names for shortcut action codes.
//
// A gesture bound to "LALT + LSHIFT + ESC" tells you which keys are sent and nothing about what
// happens. The backend ships a dictionary in the actions catalog (code -> name, chord, icon,
// group, platform), built from a real NayaFlow flash capture, and this is the lookup over it.
//
// It is populated once from /api/actions and read synchronously afterwards, because the label
// is needed inside render paths where an async lookup would flash the raw code first.

let table = {};

/** Load the dictionary from the actions catalog response. */
export function setShortcutTable(shortcuts) {
  table = shortcuts || {};
}

/**
 * Populate from a module ACTIONS list instead of the catalog.
 *
 * The Modules page never fetches the catalog -- it loads /api/modules, whose actions already
 * carry name/chord/icon for every dictionary entry. Without this the page would render raw
 * codes until something else happened to load the catalog.
 */
export function setShortcutTableFromActions(actions) {
  const next = {};
  for (const a of actions || []) {
    if (a && a.code && a.name && a.chord) {
      next[a.code] = { name: a.name, chord: a.chord, icon: a.icon,
                       group: a.group, platform: a.platform };
    }
  }
  if (Object.keys(next).length) table = { ...table, ...next };
}

// Chords renamed for the OS the names are for (Settings > Shortcut Names), from the catalog's
// shortcutOverrides. A binding stores only the chord, and the dictionary is written for Windows,
// so without these Mission Control bound on a Mac read back as "Scroll up one line".
let overrides = {};
let overridePlatform = "any";

/** Apply the catalog's per-OS names on top of the dictionary. */
export function setShortcutOverrides(map, platform) {
  overrides = map || {};
  overridePlatform = platform || "any";
}

/** The dictionary entry for a code, renamed for the chosen OS where it differs, or null. */
export function shortcutInfo(code) {
  const c = (code || "").trim();
  const info = table[c] || null;
  const o = overrides[c];
  return info && o ? { ...info, name: o.name, platform: overridePlatform } : info;
}

/**
 * "Name (Chord)" for a chord renamed for the chosen OS, or null when it is not renamed. For
 * labels that come from an action list rather than the dictionary (the Modules page), which
 * would otherwise keep the dictionary's name.
 */
export function shortcutOverrideLabel(code) {
  const o = overrides[(code || "").trim()];
  if (!o) return null;
  const info = shortcutInfo(code);
  return info?.chord ? `${o.name} (${info.chord})` : o.name;
}

/**
 * What to show for an action code.
 *
 * Falls back to the code itself rather than to a prettified chord: a shortcut we have no name
 * for is better shown exactly as stored, so it stays recognisable against the device and does
 * not quietly look like something we understand.
 */
export function shortcutLabel(code, { withChord = false } = {}) {
  const info = shortcutInfo(code);
  if (!info) return code || "";
  return withChord ? `${info.name} (${info.chord})` : info.name;
}

/** Tooltip text: the name, the keys, and where the meaning holds. */
export function shortcutTooltip(code) {
  const info = shortcutInfo(code);
  if (!info) return code || "";
  const where = info.platform === "win" ? " — Windows"
    : info.platform === "mac" ? " — macOS" : "";
  return `${info.name}\n${info.chord}${where}`;
}
