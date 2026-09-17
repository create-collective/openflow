import IconButton from "./IconButton";

// A message set apart from the content: an explanation, a caveat, a result, an error. `tone`
// draws the left rule (info = accent, ok, warn = amber, err); `size` sm is the compact note
// inside a panel (a palette tab's caveat, a stale-reading warning); `onDismiss` adds the "x".
export default function Notice({ tone = "info", size = "md", onDismiss, className = "", children, ...rest }) {
  const cls = [
    "ui-notice",
    tone !== "info" ? `ui-notice-${tone}` : "",
    size !== "md" ? `ui-notice-${size}` : "",
    onDismiss ? "ui-notice-dismissable" : "",
    className,
  ].filter(Boolean).join(" ");
  return (
    <div {...rest} className={cls} role={tone === "err" ? "alert" : undefined}>
      {onDismiss ? <span className="ui-notice-body">{children}</span> : children}
      {onDismiss && <IconButton plain size="sm" title="Dismiss" onClick={onDismiss}>✕</IconButton>}
    </div>
  );
}
