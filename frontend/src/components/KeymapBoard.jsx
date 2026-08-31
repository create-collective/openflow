import { useMemo } from "react";
import { buildLayout } from "../lib/layout";
import { keyLegend } from "../lib/keylabels";

// Shared split-columnar board. Renders one layer's keys at their real physical
// positions (variable widths, 2u inner keys, thumb arc). Used by Bindings + Color.
//   keysByPosition: { [positionId]: { colorHex, binding } }
//   mode: "bindings" | "color"
//   moduleLabels: { left, right } optional labels for the center module slots
//   onSelectKey(positionId), onSelectModule(side)
export default function KeymapBoard({
  keysByPosition = {},
  mode = "bindings",
  selectedPosition = null,
  onSelectKey = () => {},
  onSelectModule = null,
  moduleLabels = {},
  unitPx = 46,
}) {
  const layout = useMemo(() => buildLayout(), []);
  const px = (u) => u * unitPx;
  const pad = 3; // px inset between adjacent keys

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
              left: px(k.x) + pad / 2,
              top: px(k.y) + pad / 2,
              width: px(k.w) - pad,
              height: px(k.h) - pad,
              transform: k.rot ? `rotate(${k.rot}deg)` : undefined,
              background: showColor ? color : undefined,
              color: showColor ? "#04121a" : undefined,
            }}
          >
            {legend.sub && <span className="kb-sub">{legend.sub}</span>}
            <span className="kb-main">{legend.main}</span>
          </button>
        );
      })}

      {layout.modules.map((m) => (
        <button
          key={m.id}
          className={"kb-module" + (onSelectModule ? " clickable" : "")}
          title={`${m.id} module — configure`}
          onClick={() => onSelectModule && onSelectModule(m.id)}
          style={{
            position: "absolute",
            left: px(m.x) + pad / 2,
            top: px(m.y) + pad / 2,
            width: px(m.w) - pad,
            height: px(m.h) - pad,
          }}
        >
          <span className="kb-module-icon">◉</span>
          <span className="kb-module-label">{moduleLabels[m.id] || "Module"}</span>
        </button>
      ))}
    </div>
  );
}
