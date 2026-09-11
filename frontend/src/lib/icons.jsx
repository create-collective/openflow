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

export function iconUrl(name) {
  return `${import.meta.env.BASE_URL}icons/action/${name}.svg`;
}

/** The icon itself. `size` in px; colour follows `color` of the parent. */
export function ActionIcon({ name, size = 20, className = "", title, style }) {
  if (!name) return null;
  const url = `url("${iconUrl(name)}")`;
  return (
    <span
      className={"naya-icon" + (className ? " " + className : "")}
      role="img"
      aria-label={title || name}
      title={title}
      style={{ width: size, height: size, WebkitMaskImage: url, maskImage: url, ...style }}
    />
  );
}
