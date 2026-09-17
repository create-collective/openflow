import Disclosure from "./Disclosure";
import IconButton from "./IconButton";

// A message set apart from the content, at one of three levels of emphasis (owner's rule,
// 2026-09-17): a Badge says STATUS; a quiet notice (tone info / ok) says a LIMITATION, as a
// card with an icon, a title, one line of consequence and the technical why behind "Details";
// a prominent one (tone warn / err) says a FAILURE or something destructive, tinted, with the
// next action beside it. `title` is the one-line claim; the children are the consequence;
// `details` (with `detailsLabel`) is the explanation, collapsed; `action` is the button that
// fixes it ("Read again"); `icon` names one of the glyphs below or is a node. `size` sm is
// the compact inline note inside a panel; `onDismiss` adds the "x".
const GLYPH = {
  // Tabler Icons (MIT, Pawel Kuna): info-circle, circle-check, alert-triangle, circle-x,
  // clock, lock.
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v4h1" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="M9 12l2 2l4-4" /></>,
  warn: <><path d="M12 9v4M12 17h.01" /><path d="M10.24 3.96L2.34 17.16a2 2 0 0 0 1.72 3h15.88a2 2 0 0 0 1.72-3L13.76 3.96a2 2 0 0 0-3.52 0z" /></>,
  err: <><circle cx="12" cy="12" r="9" /><path d="M10 10l4 4M14 10l-4 4" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><circle cx="12" cy="16" r="1" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
};
const DEFAULT_GLYPH = { info: "info", ok: "check", warn: "warn", err: "err" };

export function NoticeGlyph({ name }) {
  const g = GLYPH[name];
  if (!g) return null;
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {g}
    </svg>
  );
}

export default function Notice({
  tone = "info", size = "md", icon, title, details, detailsLabel = "Details", action,
  onDismiss, className = "", children, ...rest
}) {
  const cls = [
    "ui-notice",
    tone !== "info" ? `ui-notice-${tone}` : "",
    size !== "md" ? `ui-notice-${size}` : "",
    className,
  ].filter(Boolean).join(" ");
  const glyph = icon === undefined ? DEFAULT_GLYPH[tone] : icon;
  return (
    <div {...rest} className={cls} role={tone === "err" ? "alert" : undefined}>
      {glyph !== null && glyph !== false && (
        <span className="ui-notice-icon">{typeof glyph === "string" ? <NoticeGlyph name={glyph} /> : glyph}</span>
      )}
      <div className="ui-notice-main">
        {title && <div className="ui-notice-title">{title}</div>}
        {children !== undefined && children !== null && children !== false && (
          <div className="ui-notice-body">{children}</div>
        )}
        {details && <Disclosure className="ui-notice-details" label={detailsLabel}>{details}</Disclosure>}
      </div>
      {action && <span className="ui-notice-action">{action}</span>}
      {onDismiss && <IconButton plain size="sm" title="Dismiss" onClick={onDismiss}>✕</IconButton>}
    </div>
  );
}
