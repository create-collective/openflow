import iconNames from "./iconNames.json";

// NayaFlow's keycap icons, one SVG per icon name under /icons/action/ (copied by
// tools/import_nayaflow_icons.py, provenance in that folder). The catalog carries each
// action's icon name (`icon`, from the palette scrape); this decides whether to draw it and
// draws it through a CSS mask so the vendor's white fills take the theme's text colour.

const HAVE = new Set(iconNames);

// Letters and digits were held back as text on the grounds that a glyph is crisper than a drawn
// one. It made them the ODD ONES OUT: every other legend on the board is a Naya icon at icon
// size, so the alphanumerics rendered in our own font at our own size and the board looked like
// two different keyboards. Naya ships all 26 letters and NUMBER_0-9, so they are drawn too, and
// the set is internally consistent until we have an icon set of our own.
/** The icon name to draw for an action code, or null when there is no icon for it. */
export function iconNameFor(code, names) {
  const entry = names && names[code];
  const icon = entry && entry.icon;
  if (!icon || !HAVE.has(icon)) return null;
  return icon;
}

// Naya draws WORD legends (Esc, Del, Home) at a fixed ~7-unit type size inside the same 40-unit
// box that holds a ~17-unit single letter, so next to "A" they render at about half height. The
// short words are worst: "Esc" and "Del" fill barely a third of their box, while "Home" and
// "Insert" at the same type size are nearly twice as wide and already look right.
//
// Measured from the path data of all 860 icons, then scaled so the type reaches ~13 units without
// the word exceeding 36 of the 40 available:  scale = min(13 / inkHeight, 36 / inkWidth).
// Anything that lands at or below 1.0 is left alone, which is why PG_UP and the JIS delete
// variants are absent -- they already fill the width. Symbols in the same height band (SPACE,
// UNDERSCORE, TILDE, the arrows) are deliberately excluded: they are flat shapes, not small type,
// and scaling them by height would be wrong.
//
// This enlarges the MASK ARTWORK, not the element, so nothing reflows.
const WORDMARK_SCALE = {
  ESC: 1.83, DELETE: 1.78, END: 1.78, LCTRL_MAC: 1.86,
  HOME: 1.36, INSERT: 1.37, MAC_DELETE: 1.24,
};

export function iconUrl(name) {
  return `${import.meta.env.BASE_URL}icons/action/${name}.svg`;
}

/** The icon itself. `size` in px; colour follows `color` of the parent. */
export function ActionIcon({ name, size = 20, className = "", title, style }) {
  if (!name) return null;
  const url = `url("${iconUrl(name)}")`;
  const scale = WORDMARK_SCALE[name];
  const mask = scale ? { WebkitMaskSize: `${scale * 100}%`, maskSize: `${scale * 100}%` } : null;
  return (
    <span
      className={"naya-icon" + (className ? " " + className : "")}
      role="img"
      aria-label={title || name}
      title={title}
      style={{ width: size, height: size, WebkitMaskImage: url, maskImage: url, ...mask, ...style }}
    />
  );
}
