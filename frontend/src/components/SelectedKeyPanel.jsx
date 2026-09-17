import { actionText } from "../lib/keylabels";
import { ActionIcon, iconNameFor } from "../lib/icons";
import Badge from "./ui/Badge";
import IconButton from "./ui/IconButton";

// The bottom-left binding editor: the selected key's Behavior -> Action rows.
// Pick a behavior slot (Tap/Hold enabled; richer OneKey slots coming soon),
// then choose an action in the palette to fill that slot.
export default function SelectedKeyPanel({
  label,
  bindings = {},
  slots = [],
  activeSlot,
  onSelectSlot,
  onClearSlot,
  layerMap = {},
  names = {},          // catalog.names: code -> {label, name, tooltip, alias}
}) {
  return (
    <div className="skp">
      <div className="skp-title">key {label ? `(${label})` : ""}</div>
      <div className="skp-head">
        <span>Behavior</span>
        <span className="skp-arrow">→</span>
        <span>Action</span>
      </div>

      {slots.map((slot) => {
        const b = bindings[slot.id];
        const active = activeSlot === slot.id;
        const disabled = !slot.enabled;
        return (
          <div
            key={slot.id}
            className={
              "skp-row" + (active ? " selected" : "") + (disabled ? " disabled" : "")
            }
            onClick={() => !disabled && onSelectSlot(slot.id)}
          >
            <span className="skp-beh">
              {slot.label}
              {!slot.enabled && (
                <Badge style={{ marginLeft: 8 }}>
                  {slot.experimental ? "experimental" : "soon"}
                </Badge>
              )}
            </span>
            <span className="skp-arrow">→</span>
            {(() => {
              const text = b ? actionText(b, layerMap) : "Unassigned";
              const nf = b && names[b.actionCode];
              const name = nf?.name && nf.name !== text ? nf.name : null;
              return (
                <span className="skp-act" title={nf ? [nf.name, nf.tooltip, `(${b.actionCode})`].filter(Boolean).join("\n") : undefined}>
                  <ActionIcon name={b && iconNameFor(b.actionCode, names)} size={14} className="inline" />
                  {text}
                  {name && <span className="skp-act-name"> — {name}</span>}
                </span>
              );
            })()}
            {b && slot.enabled && (
              <IconButton
                size="sm"
                tone="danger"
                title="Clear this slot"
                onClick={(e) => {
                  e.stopPropagation();
                  onClearSlot(slot.id);
                }}
              >
                ✕
              </IconButton>
            )}
          </div>
        );
      })}

      {!label && <div className="skp-hint">Select a key on the map to edit its bindings.</div>}
    </div>
  );
}
