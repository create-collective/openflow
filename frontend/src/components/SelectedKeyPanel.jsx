import { keyLegend } from "../lib/keylabels";

// The bottom-left binding editor: shows the selected key's physical label and
// its Behavior -> Action row(s). Phase-2 currently edits the single primary
// binding (real data only uses the 'press' slot); the row UI is laid out so
// additional behavior slots (Tap/Hold/...) can be added later.
export default function SelectedKeyPanel({ label, binding, onClear }) {
  const legend = keyLegend(binding);
  const actionText = binding ? (binding.actionCode || "—") : "Unassigned";

  return (
    <div className="skp">
      <div className="skp-title">key {label ? `(${label})` : ""}</div>
      <div className="skp-head">
        <span>Behavior</span>
        <span className="skp-arrow">→</span>
        <span>Action</span>
      </div>
      <div className="skp-row selected">
        <span className="skp-beh">{binding?.behavior || "press"}</span>
        <span className="skp-arrow">→</span>
        <span className="skp-act">{actionText}</span>
      </div>
      {binding && (
        <button className="btn danger skp-clear" onClick={onClear}>
          Clear binding
        </button>
      )}
      {!binding && (
        <div className="skp-hint">Pick an action from the palette to bind this key.</div>
      )}
    </div>
  );
}
