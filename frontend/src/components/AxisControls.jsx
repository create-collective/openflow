// One axis gesture: its two directions, and what each one does.
//
// An axis gesture is TWO device fields, one per direction, and either can hold a keypress
// instead of the motion record. That is what NayaFlow calls splitting a gesture -- confirmed by
// capture, where splitting horizontal:track turned fields 0x07 and 0x08 into independent
// keypress records.
//
// Invert writes the opposite selector signs. There is no invert flag in the config, which is
// why NayaFlow's own invert control does nothing: it never writes anything for it.
export default function AxisControls({ axis, actions, onSetHalf, onInvert, busy }) {
  const keyActions = actions.filter((a) => a.actionType === "key" || a.actionType === "keypress");
  const label = (axis.behavior || "").split(":")[0].replace(/_/g, " ");

  const half = (side, code, field) => (
    <div className="axis-half" key={side}>
      <span className="axis-dir" title={`device field 0x${field.toString(16).padStart(2, "0")}`}>
        {side === "-" ? "◀ / ▲" : "▶ / ▼"}
      </span>
      <select
        value={code || ""}
        disabled={busy}
        onChange={(e) => onSetHalf(axis.behavior, side, e.target.value || null)}
      >
        <option value="">motion (default)</option>
        {keyActions.map((a) => (
          <option key={a.code} value={a.code}>{a.label || a.code}</option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="axis-row">
      <div className="axis-head">
        <span className="axis-name">{label}</span>
        <label className="axis-invert" title="Writes the opposite direction to both fields.">
          <input type="checkbox" checked={!!axis.invert} disabled={busy}
            onChange={(e) => onInvert(axis.behavior, e.target.checked)} />
          invert
        </label>
        {axis.split && <span className="gesture-badge flashable" title="One or both directions are bound to a key instead of motion.">split</span>}
      </div>
      <div className="axis-halves">
        {half("-", axis.minus, axis.fields["-"])}
        {half("+", axis.plus, axis.fields["+"])}
      </div>
    </div>
  );
}
