import Badge from "../ui/Badge";
import IconButton from "../ui/IconButton";
import { axisHalfId, axisHalfNames, displayAction, statusBadge } from "../../lib/moduleLabels";
import { DeviceBadge } from "./GestureRow";

// The two directions of a split axis, one row each. A half is not a binding row, so it has no
// binding id: it is addressed by behavior and direction, with a synthetic selection id so the
// palette can target it like any other row.
export default function AxisHalfRows({ axis, selectedBindingId, onSelect, onClear, deviceByGesture, labelFor }) {
  const [minusName, plusName] = axisHalfNames(axis.behavior);
  // With invert on, name the direction the half NOW drives rather than a stale label.
  const motionOf = (side) => {
    const d = side === "-" ? axis.defaultMinus : axis.defaultPlus;
    const eff = axis.invert ? (side === "-" ? axis.defaultPlus : axis.defaultMinus) : d;
    return (eff || "").replace(/_/g, " ").toLowerCase();
  };
  const badge = statusBadge({ flashable: true });
  return ["-", "+"].map((side) => {
    const selId = axisHalfId(axis.behavior, side);
    const code = side === "-" ? axis.minus : axis.plus;
    return (
      <div className={"skp-row" + (selectedBindingId === selId ? " selected" : "")}
        key={axis.behavior + side}
        onClick={() => onSelect(selId)}>
        <span className="skp-beh skp-beh-half">
          {side === "-" ? minusName : plusName}
        </span>
        <Badge size="xs" tone={badge.tone} title={badge.title}>{badge.text}</Badge>
        <DeviceBadge dev={deviceByGesture[`${axis.behavior}:${side}`]} />
        <span className="skp-arrow">→</span>
        <span className={"skp-act" + (code ? "" : " unset")}
          title={`device field 0x${axis.fields[side].toString(16).padStart(2, "0")}`}>
          {code ? displayAction(code, labelFor).text
            : (motionOf(side) ? `motion — ${motionOf(side)}` : "motion")}
        </span>
        {/* The selected half, when it holds a key: the x puts the direction back to motion. */}
        {selectedBindingId === selId && onClear && !!code && (
          <IconButton size="sm" tone="danger" className="gesture-clear" title="Back to motion"
            onClick={(e) => { e.stopPropagation(); onClear(); }}>✕</IconButton>
        )}
      </div>
    );
  });
}
