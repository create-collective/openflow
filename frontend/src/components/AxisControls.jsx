// An axis gesture, rendered the way the dial is: one row until you split it.
//
// The gesture occupies TWO device fields, one per direction, and either can hold a keypress
// instead of the motion record — that is what NayaFlow calls splitting, confirmed by capture.
// Unsplit it reads as a single row saying what the motion does; tick split and the two
// directions appear as their own rows, exactly like the dial's clockwise/counter-clockwise.
//
// Invert writes the opposite selector signs. There is no invert flag in the config, which is why
// NayaFlow's own invert control does nothing — it never writes anything for it.
import { useEffect, useState } from "react";

const HALF_LABEL = {
  vertical: ["Up", "Down"],
  horizontal: ["Left", "Right"],
  rotate: ["Rotate left", "Rotate right"],
};

export default function AxisControls({ axis, actions, onSetHalf, onInvert, busy }) {
  // `split` is derived server-side from whether a half actually holds a key, so there is no
  // stored "split, but nothing bound yet" state -- and that is the state the user is in the
  // moment they tick the box. So the checkbox is local, seeded from the server's view and
  // re-seeded whenever it changes underneath (a read, a profile switch).
  const [split, setSplit] = useState(!!axis.split);
  useEffect(() => { setSplit(!!axis.split); }, [axis.split]);

  const keyActions = actions.filter((a) => a.actionType === "key" || a.actionType === "keypress");
  const head = (axis.behavior || "").split(":")[0];
  const label = head.replace(/_/g, " ");
  const [minusName, plusName] = HALF_LABEL[head] || ["–", "+"];

  // What a half does when it is NOT bound to a key: the matching side of the combined binding.
  // With invert on, name the direction that half now drives rather than a stale label.
  const motionOf = (side) => {
    const d = side === "-" ? axis.defaultMinus : axis.defaultPlus;
    const eff = axis.invert ? (side === "-" ? axis.defaultPlus : axis.defaultMinus) : d;
    return (eff || "").replace(/_/g, " ").toLowerCase();
  };

  const halfRow = (side, code, field, name) => (
    <div className="skp-row" key={side}>
      <span className="skp-beh" style={{ textTransform: "none", paddingLeft: 18 }}>
        {name}
      </span>
      <span className="skp-arrow">→</span>
      <select
        className="mac-input mod-action"
        value={code || ""}
        disabled={busy}
        title={`device field 0x${field.toString(16).padStart(2, "0")}`}
        onChange={(e) => onSetHalf(axis.behavior, side, e.target.value || null)}
      >
        <option value="">{motionOf(side) ? `motion — ${motionOf(side)}` : "motion"}</option>
        {keyActions.map((a) => (
          <option key={a.code} value={a.code}>{a.label || a.code}</option>
        ))}
      </select>
    </div>
  );

  return (
    <>
      <div className="skp-row" style={{ cursor: "default" }}>
        <span className="skp-beh" style={{ textTransform: "capitalize" }}>{label}</span>
        <span className="skp-arrow">→</span>
        <select
          className="mac-input mod-action"
          value=""
          disabled
          title={
            split
              ? "Split is on — each direction is set separately below."
              : `${motionOf("-")} / ${motionOf("+")}`
          }
        >
          <option value="">
            {split
              ? "split — set per direction below"
              : `motion — ${motionOf("-")} / ${motionOf("+")}`}
          </option>
        </select>
        <label className="split-toggle" title="Bind each direction separately.">
          <input
            type="checkbox"
            checked={split}
            disabled={!!busy}
            onChange={(e) => {
              setSplit(e.target.checked);
              // Unticking clears both halves back to motion. Nothing needs stashing: the
              // combined record is rebuilt from the axis category and its direction signs.
              if (!e.target.checked) {
                onSetHalf(axis.behavior, "-", null);
                onSetHalf(axis.behavior, "+", null);
              }
            }}
          />
          split
        </label>
        <label className="split-toggle" title="Writes the opposite direction to both fields.">
          <input type="checkbox" checked={!!axis.invert} disabled={!!busy}
            onChange={(e) => onInvert(axis.behavior, e.target.checked)} />
          invert
        </label>
      </div>

      {split && halfRow("-", axis.minus, axis.fields["-"], minusName)}
      {split && halfRow("+", axis.plus, axis.fields["+"], plusName)}
    </>
  );
}
