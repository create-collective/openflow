// A key/value row. `layout` split puts the value at the far edge (a card's few facts); grid
// puts every value on a 150 px label column so a long list lines up (the Information page).
// A row with nothing to show renders nothing, so callers can list facts they may not have.
// `mono` is on by default (versions, ports, addresses); pass false for prose.
export function KVRow({ k, v, mono = true, layout = "split", title, className = "", children, ...rest }) {
  const value = children ?? v;
  if (value === null || value === undefined || value === "") return null;
  const cls = ["ui-kv", `ui-kv-${layout}`, className].filter(Boolean).join(" ");
  return (
    <div {...rest} className={cls} title={title}>
      <span className="ui-kv-k">{k}</span>
      <span className={"ui-kv-v" + (mono ? " mono" : "")}>{value}</span>
    </div>
  );
}

// Groups rows so the last one drops its rule, and carries the layout to every row.
export function KVList({ layout = "split", className = "", children, ...rest }) {
  const cls = ["ui-kv-list", `ui-kv-list-${layout}`, className].filter(Boolean).join(" ");
  return <div {...rest} className={cls}>{children}</div>;
}
