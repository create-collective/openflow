// One tab strip for the four that were hand-built.
//
// `variant`: vertical (the Settings sidebar), segmented (the Information page's chooser and
// the diagnostics half picker), underline (bindings | settings on a module), pills (the action
// palette's icon squares; `label` beside an `icon` is what the storyboard's icon+label pill
// becomes). `items`: [{ id, label, icon, title, disabled }]. Keyboard: arrows move between
// enabled tabs, Home/End jump; the strip is a real tablist for assistive tech.
export default function Tabs({ items, value, onChange, variant = "underline", className = "", ariaLabel, ...rest }) {
  const enabled = items.filter((t) => !t.disabled);

  function onKeyDown(e) {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1, Home: "first", End: "last" };
    const move = keys[e.key];
    if (move === undefined || !enabled.length) return;
    e.preventDefault();
    const i = enabled.findIndex((t) => t.id === value);
    const next = move === "first" ? 0
      : move === "last" ? enabled.length - 1
      : (i + move + enabled.length) % enabled.length;
    onChange(enabled[next].id);
    e.currentTarget.querySelectorAll('[role="tab"]')[items.indexOf(enabled[next])]?.focus();
  }

  const cls = ["ui-tabs", `ui-tabs-${variant}`, className].filter(Boolean).join(" ");
  return (
    <div {...rest} role="tablist" aria-label={ariaLabel} className={cls} onKeyDown={onKeyDown}>
      {items.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            className={"ui-tab" + (active ? " active" : "")}
            title={t.title}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
          >
            {t.icon}
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
