// A small label that says what something IS: FLASHABLE, APP ONLY, VERIFIED, experimental, a
// side, a count. `tone` carries the meaning (ok / warn / err / accent / neutral); `size` sm is
// the pill (11 px, rounded), xs the compact tag beside a setting label (10 px); `variant` solid
// is the filled accent chip ("live" in the bay picker). Labels are the caller's, unchanged.
export default function Badge({
  tone = "neutral",
  size = "sm",
  variant = "soft",
  className = "",
  children,
  ...rest
}) {
  const cls = [
    "ui-badge",
    `ui-badge-${tone}`,
    `ui-badge-${size}`,
    variant !== "soft" ? `ui-badge-${variant}` : "",
    className,
  ].filter(Boolean).join(" ");
  return <span {...rest} className={cls}>{children}</span>;
}
