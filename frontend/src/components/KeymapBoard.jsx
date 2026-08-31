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
  unitPx = 42,
}) {
  const layout = useMemo(() => buildLayout(), []);
  const px = (u) => u * unitPx;
  const pad = 7; // px inset -> gap between adjacent keys (breathing room)

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

      {mode === "color" &&
        layout.ledZones.map((z) => {
          const data = keysByPosition[z.positionId];
          const color = data?.colorHex;
          return (
            <button
              key={z.positionId}
              className={"kb-led" + (selectedPosition === z.positionId ? " selected" : "")}
              title={`LED ${z.positionId}`}
              onClick={() => onSelectKey(z.positionId)}
              style={{
                position: "absolute",
                left: px(z.x) + pad / 2,
                top: px(z.y) + pad / 2,
                width: px(z.w),
                height: px(z.h),
                background: color || "var(--neutral20)",
              }}
            />
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
