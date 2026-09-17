import Button from "../ui/Button";
import { displayAction } from "../../lib/moduleLabels";

// What the palette is about to write to, as the strip the storyboard draws over the palette:
// "Selected gesture: 2 Fingers / Tap | Current binding: F21". Bindings has SelectedKeyPanel for
// exactly this; here the only cue used to be a .selected class on a row that can sit most of
// a screen above the palette, so it was easy to pick an action into nothing, or into the
// wrong row. Deliberately not SelectedKeyPanel: that is a four-slot table, this is one row.
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
      <span className="mod-target-part">
        <span className="mod-target-label">Selected gesture:</span>
        <strong className="mod-target-name">{name}</strong>
      </span>
      <span className="mod-target-sep" aria-hidden="true" />
      <span className="mod-target-part">
        <span className="mod-target-label">Current binding:</span>
        <span className={"skp-act" + (shown.muted ? " unset" : "")} title={shown.title}>{shown.text}</span>
      </span>
      <Button size="sm" className="mod-target-clear" onClick={onDone}>Done</Button>
    </div>
  );
}
