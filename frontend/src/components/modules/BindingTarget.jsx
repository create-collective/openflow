import Button from "../ui/Button";
import IconButton from "../ui/IconButton";
import { displayAction } from "../../lib/moduleLabels";

// What the palette is about to write to, as the strip the storyboard draws over the palette:
// "Selected gesture: 2 Fingers / Tap | Current binding: F21". Bindings has SelectedKeyPanel for
// exactly this; here the only cue used to be a .selected class on a row that can sit most of
// a screen above the palette, so it was easy to pick an action into nothing, or into the
// wrong row. Deliberately not SelectedKeyPanel: that is a four-slot table, this is one row.
// The x beside the binding clears it (an axis half goes back to motion): without it the only
// way to empty a gesture was to bind something else over it.
export default function BindingTarget({ selectedBinding, name, labelFor, onDone, onClear }) {
  if (!selectedBinding) {
    return (
      <div className="mod-target">
        <span className="mod-target-label">Select a gesture above to bind it.</span>
      </div>
    );
  }
  const shown = displayAction(selectedBinding.actionCode, labelFor);
  // An empty axis half is not "Unassigned", it is motion again.
  const text = !selectedBinding.actionCode && selectedBinding.unsetText ? selectedBinding.unsetText : shown.text;
  const clearTitle = selectedBinding.axisHalf ? "Back to motion" : "Clear this binding";
  return (
    <div className="mod-target armed">
      <span className="mod-target-part">
        <span className="mod-target-label">Selected gesture:</span>
        <strong className="mod-target-name">{name}</strong>
      </span>
      <span className="mod-target-sep" aria-hidden="true" />
      <span className="mod-target-part">
        <span className="mod-target-label">Current binding:</span>
        <span className={"skp-act" + (shown.muted ? " unset" : "")} title={shown.title}>{text}</span>
        {onClear && !!selectedBinding.actionCode && (
          <IconButton size="sm" tone="danger" className="mod-target-x" title={clearTitle} onClick={onClear}>✕</IconButton>
        )}
      </span>
      <Button size="sm" className="mod-target-clear" onClick={onDone}>Done</Button>
    </div>
  );
}
