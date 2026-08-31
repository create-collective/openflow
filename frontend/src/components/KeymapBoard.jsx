import { useMemo } from "react";
import { buildLayout } from "../lib/layout";
import { keyLegend } from "../lib/keylabels";

// Shared split-columnar board. Renders one layer's keys at their physical
// positions. Used by both Bindings and Color pages.
//   keysByPosition: { [positionId]: { colorHex, binding } }
//   mode: "bindings" | "color"
//   selectedPosition, onSelectKey(positionId)
export default function KeymapBoard({
  keysByPosition = {},
  mode = "bindings",
  selectedPosition = null,
  onSelectKey = () => {},
  remPx = 16,
}) {
  const layout = useMemo(() => buildLayout(), []);
  const scale = 0.82; // rem -> px scale for the board
  const px = (rem) => rem * remPx * scale;

  return (
    <div
      className="keymap-board"
      style={{ position: "relative", width: px(layout.width), height: px(layout.height) }}
    >
      {layout.keys.map((k) => {
        const data = keysByPosition[k.positionId];
        const legend = keyLegend(data?.binding);
        const selected = selectedPosition === k.positionId;
        const color = data?.colorHex;
        const showColor = mode === "color" && color;
        return (
          <button
            key={k.positionId}
            className={"kb-key" + (selected ? " selected" : "")}
            title={`${k.label} (pos ${k.positionId})`}
            onClick={() => onSelectKey(k.positionId)}
            style={{
              position: "absolute",
              left: px(k.x),
              top: px(k.y),
              width: px(layout.unit),
              height: px(layout.unit),
              background: showColor ? color : undefined,
              color: showColor ? "#04121a" : undefined,
            }}
          >
            {legend.sub && <span className="kb-sub">{legend.sub}</span>}
            <span className="kb-main">{legend.main}</span>
          </button>
        );
      })}
    </div>
  );
}
