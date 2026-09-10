import iconNames from "./iconNames.json";

// NayaFlow's keycap icons, one SVG per icon name under /icons/action/ (copied by
// tools/import_nayaflow_icons.py, provenance in that folder). The catalog carries each
// action's icon name (`icon`, from the palette scrape); this decides whether to draw it and
// draws it through a CSS mask so the vendor's white fills take the theme's text colour.

const HAVE = new Set(iconNames);

// Letters and digits stay as text: crisper than a drawn glyph, and what a keycap already says.
const TEXT_LIKE = /^(?:[A-Z]|NUMBER_\d)$/;

/** The icon name to draw for an action code, or null when text is the better legend. */
export function iconNameFor(code, names) {
  const entry = names && names[code];
  const icon = entry && entry.icon;
  if (!icon || !HAVE.has(icon) || TEXT_LIKE.test(icon)) return null;
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
