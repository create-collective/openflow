import Button from "../ui/Button";
import { displayAction } from "../../lib/moduleLabels";

// What the palette is about to write to. Bindings has SelectedKeyPanel for exactly this; here
// the only cue was a .selected class on a row that can sit most of a screen above the palette,
// so it was easy to pick an action into nothing, or into the wrong row. Deliberately not
// SelectedKeyPanel: that is a four-slot table, this is one row.
export default function BindingTarget({ selectedBinding, name, labelFor, onDone }) {
  if (!selectedBinding) {
    return (
      <div className="mod-target">
        <span className="mod-target-label">Select a gesture above to bind it.</span>
      </div>
    );
  }
  const shown = displayAction(selectedBinding.actionCode, labelFor);
  return (
    <div className="mod-target armed">
      <span className="mod-target-label">Binding</span>
      <strong className="mod-target-name">{name}</strong>
      <span className="skp-arrow">→</span>
      <span className={"skp-act" + (shown.muted ? " unset" : "")} title={shown.title}>{shown.text}</span>
      <Button className="mod-target-clear" onClick={onDone}>Done</Button>
    </div>
  );
}
