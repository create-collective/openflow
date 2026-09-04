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

/** The dictionary entry for a code, or null. */
export function shortcutInfo(code) {
  return table[(code || "").trim()] || null;
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
