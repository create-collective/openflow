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

// The behaviour glyphs: a hand with the index finger raised (Tabler Icons "hand-finger",
// MIT, Pawel Kuna), the same hand every time, with a small modifier that says what the finger
// does: one arc over the tip for a tap, two for a double tap, a bar under the hand for a hold,
// and the combinations. The hand is a designer's; only the arcs and the bar are ours.
const HAND = [
  "M8 13v-8.5a1.5 1.5 0 0 1 3 0v7.5",
  "M11 11.5v-2a1.5 1.5 0 1 1 3 0v2.5",
  "M14 10.5a1.5 1.5 0 0 1 3 0v1.5",
  "M17 11.5a1.5 1.5 0 0 1 3 0v4.5a6 6 0 0 1 -6 6h-2h.208a6 6 0 0 1 -5.012 -2.7a69.74 69.74 0 0 1 -.196 -.3c-.312 -.479 -1.407 -2.388 -3.286 -5.728a1.5 1.5 0 0 1 .536 -2.022a1.867 1.867 0 0 1 2.28 .28l1.47 1.47",
];

function BehaviorGlyph({ id }) {
  const taps = id.startsWith("double") ? 2 : id === "hold" ? 0 : 1;
  const hold = id.includes("hold");
  return (
    <svg className="keyband-glyph" width="24" height="30" viewBox="0 -5 24 30" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {HAND.map((d) => <path key={d} d={d} />)}
      {taps >= 1 && <path d="M5.5 1.5a5.7 5.7 0 0 1 8 0" />}
      {taps === 2 && <path d="M3.5 -1.5a8.5 8.5 0 0 1 12 0" />}
      {hold && <path d="M6.5 24.5h11" strokeWidth="2" />}
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
          {/* A slot the catalog has not enabled (Double Tap + Hold) is not shown at all: a
              card marked "soon" that stays soon is a promise on every screen. */}
          {slots.filter((slot) => slot.enabled).map((slot) => {
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
