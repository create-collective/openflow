// "▸ Why is this unavailable?": one quiet line that opens into the explanation beneath it.
// The technical why of a limitation lives here, so the notice above it can keep to the
// consequence and the next action. A native <details>, so it needs no state, works from the
// keyboard and is announced as expandable; only the marker is ours, drawn in the accent.
export default function Disclosure({ label, open, className = "", children, ...rest }) {
  const cls = ["ui-disclosure", className].filter(Boolean).join(" ");
  return (
    <details {...rest} className={cls} open={open}>
      <summary className="ui-disclosure-summary">{label}</summary>
      <div className="ui-disclosure-body">{children}</div>
    </details>
  );
}
