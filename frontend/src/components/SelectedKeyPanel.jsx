// The bottom-left binding editor: the selected key's Behavior -> Action rows.
// Pick a behavior slot (Tap/Hold enabled; richer superkey slots coming soon),
// then choose an action in the palette to fill that slot.
export default function SelectedKeyPanel({
  label,
  bindings = {},
  slots = [],
  activeSlot,
  onSelectSlot,
  onClearSlot,
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
              {!slot.enabled && <span className="pill" style={{ marginLeft: 8 }}>soon</span>}
            </span>
            <span className="skp-arrow">→</span>
            <span className="skp-act">{b ? b.actionCode : "Unassigned"}</span>
            {b && slot.enabled && (
              <button
                className="skp-x"
                title="Clear this slot"
                onClick={(e) => {
                  e.stopPropagation();
                  onClearSlot(slot.id);
                }}
              >
                ✕
              </button>
            )}
          </div>
        );
      })}

      {!label && <div className="skp-hint">Select a key on the map to edit its bindings.</div>}
    </div>
  );
}
