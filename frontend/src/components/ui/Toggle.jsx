// An on/off control. `variant` switch is the sliding knob a setting uses (a button with
// role=switch, so it is keyboard- and screen-reader-correct); check is a labelled checkbox for
// an inline option ("Keep my timing", "Also remove unused slots"), where className and style
// dress the label and everything else reaches the input.
export default function Toggle({ checked, onChange, label, variant = "switch", disabled, title, className = "", style, ...rest }) {
  if (variant === "check") {
    const cls = ["ui-check", className].filter(Boolean).join(" ");
    return (
      <label className={cls} style={style} title={title}>
        <input {...rest} type="checkbox" checked={!!checked} disabled={disabled}
          onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  const cls = ["ui-toggle", checked ? "on" : "", className].filter(Boolean).join(" ");
  return (
    <button {...rest} type="button" role="switch" aria-checked={!!checked} aria-label={label} title={title}
      className={cls} style={style} disabled={disabled} onClick={() => onChange(!checked)}>
      <span className="ui-toggle-knob" />
    </button>
  );
}
