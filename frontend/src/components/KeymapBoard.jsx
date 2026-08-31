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
  moduleAssign = {},
  showModulePalette = false,
  onAssignModule = null,
  pickedModule = null,
  onPickModule = null,
  unitPx = 42,
}) {
  const layout = useMemo(() => buildLayout(), []);
  const px = (u) => u * unitPx;
  const pad = 7; // px inset -> gap between adjacent keys
  const MODULE_IMG = { track: "/modules/track-plain.png", touch: "/modules/touch.png", tune: "/modules/tune.png" };

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

      {layout.modules.map((m) => {
        // In color mode the module slots are RGB-addressable like keys.
        if (mode === "color") {
          const data = keysByPosition[m.positionId];
          const color = data?.colorHex;
          return (
            <button
              key={m.id}
              className={"kb-module color" + (selectedPosition === m.positionId ? " selected" : "")}
              title={`${m.id} module LED`}
              onClick={() => onSelectKey(m.positionId)}
              style={{
                position: "absolute",
                left: px(m.x) + pad / 2,
                top: px(m.y) + pad / 2,
                width: px(m.w) - pad,
                height: px(m.h) - pad,
                background: color || undefined,
              }}
            >
              {!color && <span className="kb-module-label">{m.id}</span>}
            </button>
          );
        }
        const assigned = moduleAssign[m.id];
        return (
          <button
            key={m.id}
            className={"kb-module" + (assigned ? " filled" : "") + ((assigned || onAssignModule) ? " clickable" : "") + (pickedModule ? " droptarget" : "")}
            title={assigned ? `${assigned} module — click to configure` : `${m.id} slot — drag or click-place a module`}
            onClick={() => {
              if (pickedModule && onAssignModule) onAssignModule(m.id, pickedModule);
              else if (assigned && onSelectModule) onSelectModule(assigned);
            }}
            onDragOver={(e) => { if (onAssignModule) { e.preventDefault(); } }}
            onDrop={(e) => {
              if (!onAssignModule) return;
              e.preventDefault();
              const type = e.dataTransfer.getData("text/plain");
              if (type) onAssignModule(m.id, type);
            }}
            style={{
              position: "absolute",
              left: px(m.x) + pad / 2,
              top: px(m.y) + pad / 2,
              width: px(m.w) - pad,
              height: px(m.h) - pad,
            }}
          >
            {assigned ? (
              <img src={MODULE_IMG[assigned]} alt={assigned} className="kb-module-img" />
            ) : (
              <>
                <span className="kb-module-icon">◉</span>
                <span className="kb-module-label">{m.id}</span>
              </>
            )}
          </button>
        );
      })}

      {showModulePalette &&
        layout.palette.map((p) => (
          <img
            key={p.type}
            src={MODULE_IMG[p.type]}
            alt={p.type}
            title={`Drag ${p.type} onto a slot, or click then click a slot`}
            draggable
            onDragStart={(e) => e.dataTransfer.setData("text/plain", p.type)}
            onClick={() => onPickModule && onPickModule(pickedModule === p.type ? null : p.type)}
            className={"kb-palette-mod" + (pickedModule === p.type ? " picked" : "")}
            style={{
              position: "absolute",
              left: px(p.x) + pad / 2,
              top: px(p.y) + pad / 2,
              width: px(p.w) - pad,
              height: px(p.h) - pad,
            }}
          />
        ))}
    </div>
  );
}
