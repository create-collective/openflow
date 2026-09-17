// A button that is a glyph: the row's "..." menu, a clear "x", a dismiss.
//
// `title` is required: the glyph alone says nothing to a screen reader or a tooltip. `tone`
// "danger" colours the hover red (clearing something). `reveal` hides it until its row is
// hovered: put `ui-reveal-host` on the row. `size` sm is the 12 px "x"; md the 16 px menu dots.
// `plain` drops the padding and radius for a glyph sitting in running text (a note's dismiss).
export default function IconButton({
  title,
  tone = "muted",
  size = "md",
  reveal = false,
  plain = false,
  className = "",
  type = "button",
  children,
  ...rest
}) {
  const cls = [
    "ui-iconbtn",
    tone !== "muted" ? `ui-iconbtn-${tone}` : "",
    size !== "md" ? `ui-iconbtn-${size}` : "",
    reveal ? "ui-iconbtn-reveal" : "",
    plain ? "ui-iconbtn-plain" : "",
    className,
  ].filter(Boolean).join(" ");
  return (
    <button {...rest} type={type} className={cls} title={title} aria-label={rest["aria-label"] || title}>
      {children}
    </button>
  );
}
