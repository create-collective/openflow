import { actionText, keyLegend } from "../lib/keylabels";
import { ActionIcon, iconNameFor } from "../lib/icons";
import Badge from "./ui/Badge";
import IconButton from "./ui/IconButton";

// The band between the board and the palette: the selected key on the left (its legend, its
// position, its half) and, on the right, the key's behaviours as a row of cards (Tap, Hold,
// Double Tap, Tap + Hold, and the one still to come), each showing what it does. The selected
// card is the slot the palette writes to; a bound card can be cleared. It was a vertical
// Behavior -> Action table beside the palette; the storyboard's "Selected key / Key bindings"
// band puts it between the board and the palette, which is where the eye goes next.
const HALF = { L: "Left half", R: "Right half" };

// The behaviour glyphs: a fingertip, the taps above it, a bar under a hold.
function BehaviorGlyph({ id }) {
  const taps = id.startsWith("double") ? 2 : 1;
  const hold = id.includes("hold") || id === "hold";
  return (
    <svg className="keyband-glyph" width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="10" cy="12" r="3" fill={id === "hold" ? "currentColor" : "none"} />
      {id !== "hold" && <path d="M6.5 7.5a5 5 0 0 1 7 0" />}
      {taps === 2 && <path d="M4 4.5a8.5 8.5 0 0 1 12 0" />}
      {id === "hold" && <circle cx="10" cy="12" r="6.5" />}
      {hold && id !== "hold" && <path d="M6 18h8" />}
    </svg>
  );
}

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
  const tap = bindings.tap;
  const legend = tap ? keyLegend(tap, layerMap) : null;
  const tapIcon = tap && iconNameFor(tap.actionCode, names);
  const half = label ? HALF[label[0]] : null;
  const active = slots.find((s) => s.id === activeSlot);

  return (
    <section className="keyband" aria-label="Selected key">
      <div className="keyband-sel">
        <div className="keyband-title">Selected key</div>
        {label ? (
          <div className="keyband-key">
            <div className={"keyband-cap" + (legend && !tapIcon && legend.main.length > 3 ? " long" : "")} aria-hidden="true">
              {tapIcon ? <ActionIcon name={tapIcon} size={28} /> : legend ? legend.main : label}
              {legend && legend.sub && !tapIcon && <span className="keyband-cap-sub">{legend.sub}</span>}
            </div>
            <div className="keyband-text">
              <div className="keyband-name">
                {tap ? actionText(tap, layerMap) : "Unassigned"}
                <span className="keyband-pos">{label} · {half}</span>
              </div>
              <div className="keyband-hint">
                {active
                  ? <>Assigning <strong>{active.label}</strong>: pick an action below.</>
                  : "Choose a behavior, then an action below."}
              </div>
            </div>
          </div>
        ) : (
          <div className="keyband-key">
            <div className="keyband-cap empty" aria-hidden="true">?</div>
            <div className="keyband-text">
              <div className="keyband-name">No key selected</div>
              <div className="keyband-hint">Select a key on the map to edit its bindings.</div>
            </div>
          </div>
        )}
      </div>

      <div className="keyband-slots">
        <div className="keyband-title">Key bindings</div>
        <div className="keyband-cards" role="group" aria-label="Behaviors">
          {slots.map((slot) => {
            const b = bindings[slot.id];
            const isActive = activeSlot === slot.id;
            const disabled = !slot.enabled || !label;
            const text = b ? actionText(b, layerMap) : null;
            const nf = b && names[b.actionCode];
            const name = nf?.name && nf.name !== text ? nf.name : null;
            const title = nf ? [nf.name, nf.tooltip, `(${b.actionCode})`].filter(Boolean).join("\n") : undefined;
            return (
              <div
                key={slot.id}
                className={"keyband-card ui-reveal-host" + (isActive ? " selected" : "") + (disabled ? " disabled" : "")}
              >
                <button
                  type="button"
                  className="keyband-card-btn"
                  disabled={disabled}
                  aria-pressed={isActive}
                  onClick={() => onSelectSlot(slot.id)}
                >
                  <span className="keyband-card-head">
                    <BehaviorGlyph id={slot.id} />
                    <span className="keyband-card-label">{slot.label}</span>
                    {!slot.enabled
                      ? <Badge>{slot.experimental ? "experimental" : "soon"}</Badge>
                      : isActive && <Badge tone="accent">Selected</Badge>}
                  </span>
                  {/* Text only: the big cap already shows the icon, and for a letter the
                      icon IS the letter, so icon plus text read "A A". */}
                  <span className={"keyband-act" + (b ? "" : " unset")} title={title}>
                    {text || "Unassigned"}
                    {name && <span className="keyband-act-name">{name}</span>}
                  </span>
                </button>
                {b && slot.enabled && (
                  <IconButton
                    size="sm"
                    tone="danger"
                    reveal
                    className="keyband-clear"
                    title={`Clear ${slot.label}`}
                    onClick={() => onClearSlot(slot.id)}
                  >
                    ✕
                  </IconButton>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
