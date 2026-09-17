import Button from "./Button";

// One setting's row: label and badge on the left, the control (and a Reset when the value is
// not the default) on the right, the description beneath, then anything extra (a slider).
// SettingField chooses the control; pages with a one-off control pass it in directly, which
// is what the Settings page's ten hand-built copies of this markup become.
export default function SettingRow({
  label, badge, control, desc, changed = false, onReset, resetTitle = "Reset", bare = false, className = "", children, ...rest
}) {
  // `bare`: the row's markup without the list padding and rule, for a heading-with-controls
  // that introduces something else (the device log) rather than one setting in a list.
  // Label and badge, the description beneath them, and the control beside both (the
  // storyboard's row); anything extra (a slider) runs the full width underneath.
  const cls = [bare ? "setting-bare" : "setting", className].filter(Boolean).join(" ");
  return (
    <div {...rest} className={cls}>
      <div className="setting-main">
        <div className="setting-head">
          <strong>{label}</strong>
          {badge}
        </div>
        {desc !== undefined && <div className="setting-desc">{desc}</div>}
      </div>
      {(control !== undefined || (changed && onReset)) && (
        <div className="setting-ctl">
          {changed && onReset && (
            <button type="button" className="setting-reset" title={resetTitle} onClick={onReset}>↺ Reset</button>
          )}
          {control}
        </div>
      )}
      {children}
    </div>
  );
}

export { Button };
