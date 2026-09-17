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

// The behaviour glyphs, as the storyboard draws them: a pointing finger; one arc over the tip
// for a tap, two for a double tap, press marks beside the tip for a hold.
function BehaviorGlyph({ id }) {
  const taps = id.startsWith("double") ? 2 : id === "hold" ? 0 : 1;
  const hold = id.includes("hold");
  return (
    <svg className="keyband-glyph" width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {/* the finger: a rounded stroke from the tip down, then the knuckles and the thumb */}
      <path d="M13 9.5v9" strokeWidth="3.4" />
      <path d="M13 18.5c0 1.6-.6 2.6-1.8 3.4-1.4.9-3.2.8-4.3-.3l-2.7-2.9c-.6-.7-.5-1.7.2-2.2.6-.5 1.5-.4 2 .1l1.6 1.6" />
      <path d="M13 17.5h2.4c1.2 0 2.1.9 2.1 2v.3M17.5 17.8h1.6c1.2 0 2 .9 2 2v.5M21.1 18.6c1.1 0 2 .9 2 2 0 1.4-.4 3.6-1.6 5.2-.8 1-2 1.7-3.3 1.7h-6" />
      {taps >= 1 && <path d="M8.5 6.5a6.4 6.4 0 0 1 9 0" />}
      {taps === 2 && <path d="M5.5 3.5a10.6 10.6 0 0 1 15 0" />}
      {hold && <path d="M6.5 11h3M16.5 11h3" />}
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
            {/* The block is as wide as the layer list beside the board, so the cards start
                where the board's column does; what a pick writes to is said by the palette. */}
            <div className="keyband-text">
              <div className="keyband-name">{tap ? actionText(tap, layerMap) : "Unassigned"}</div>
              <div className="keyband-pos">{label} · {half}</div>
            </div>
          </div>
        ) : (
          <div className="keyband-key">
            <div className="keyband-cap empty" aria-hidden="true">?</div>
            <div className="keyband-text">
              <div className="keyband-name">No key selected</div>
              <div className="keyband-pos">Select one on the map.</div>
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
                  <span className="keyband-card-icon"><BehaviorGlyph id={slot.id} /></span>
                  <span className="keyband-card-body">
                    <span className="keyband-card-head">
                      <span className="keyband-card-label">{slot.label}</span>
                      {!slot.enabled
                        ? <Badge>{slot.experimental ? "experimental" : "soon"}</Badge>
                        : isActive && <Badge tone="accent">Selected</Badge>}
                    </span>
                    {/* A keycap, text only: the big cap already shows the icon, and for a letter
                        the icon IS the letter, so icon plus text read "A A". */}
                    <span className={"keyband-act" + (b ? "" : " unset")} title={title}>
                      {text || "Unassigned"}
                      {name && <span className="keyband-act-name">{name}</span>}
                    </span>
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
