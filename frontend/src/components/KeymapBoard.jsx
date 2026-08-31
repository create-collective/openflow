import { keyLegend } from "../lib/keylabels";
import LayersIcon from "./LayersIcon";
import { SHAPES, POS_SHAPE } from "../lib/keyshapes";
import {
  LEFT_COLS, RIGHT_COLS, KEY_WRAPPERS, LEFT_THUMBS, RIGHT_THUMBS,
  LEFT_LEDS, RIGHT_LEDS, KEY_UNIT, REM,
} from "../lib/boardgeom";

const MODULE_IMG = { track: "/modules/track-plain.png", touch: "/modules/touch.png", tune: "/modules/tune.png" };
const NORMAL_W = 44 * KEY_UNIT; // a plain keycap's width; columns are fixed to this
                                // so wide/hex keys overflow toward center, not push neighbors

// Pick a legible legend color for a keycap painted with an LED color: dark text
// on bright keys, light text on dark ones (mirrors NayaFlow's LED view).
function contrastText(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return undefined;
  const n = parseInt(m[1], 16);
  const lum = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  return lum > 0.6 ? "#0a0a0a" : "#f5f5f5";
}

// One keycap: the exact NayaFlow SVG silhouette for its position, filled/stroked,
// with the resolved legend centered per-shape.
function KeyCap({ pos, data, mode, selected, onSelectKey, layerMap }) {
  const shape = SHAPES[POS_SHAPE[pos]] || SHAPES.Ve;
  const [, , vbw, vbh] = shape.viewBox.split(" ").map(Number);
  const w = vbw * KEY_UNIT, h = vbh * KEY_UNIT;
  const legend = keyLegend(data?.binding, layerMap);
  const color = data?.colorHex;
  const showColor = mode === "color" && color;
  const textColor = showColor ? contrastText(color) : undefined;
  const fill = showColor ? color : "var(--neutral6)";
  const stroke = selected ? "var(--accent)" : "var(--border-strong)";
  const wrap = KEY_WRAPPERS[pos] || {};
  return (
    <button
      className="kc"
      title={`pos ${pos}`}
      onClick={() => onSelectKey(pos)}
      style={{
        width: w, height: h, position: "relative", padding: 0, border: "none",
        background: "none", cursor: "pointer",
        marginTop: (wrap.pt || 0) * REM,
        filter: selected ? "drop-shadow(0 0 3px var(--accent))" : undefined,
      }}
    >
      <svg width={w} height={h} viewBox={shape.viewBox} fill="none"
        style={{ position: "absolute", inset: 0, display: "block", overflow: "visible" }}>
        {shape.rect ? (
          <rect x={shape.rect.x} y={shape.rect.y} width={shape.rect.w} height={shape.rect.h}
            rx={shape.rect.rx} fill={fill} stroke={stroke} strokeWidth="2" />
        ) : (
          <path d={shape.d} fill={fill} stroke={stroke} strokeWidth="2" />
        )}
      </svg>
      {legend.layer && (
        <span className="kc-legend kc-layer" style={{ top: shape.legend.top, left: shape.legend.left, color: textColor }}>
          <LayersIcon size={14} />
          <span className="kc-layernum">{legend.layer.num}</span>
        </span>
      )}
      {!legend.layer && (legend.main || legend.sub) && (
        <span className="kc-legend" style={{ top: shape.legend.top, left: shape.legend.left, color: textColor }}>
          {legend.sub && <span className="kc-sub" style={{ color: textColor }}>{legend.sub}</span>}
          <span className="kc-main">{legend.main}</span>
        </span>
      )}
    </button>
  );
}

function Column({ col, align, ...kp }) {
  // Fixed column width so wide (2u space) and hex keys overflow toward the center
  // instead of pushing neighbours. Left half aligns keys to the outer (left) edge;
  // right half to the outer (right) edge — mirroring NayaFlow.
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 0.1 * REM,
      alignItems: align === "end" ? "flex-end" : "flex-start",
      width: NORMAL_W, flexShrink: 0,
      marginTop: (col.mt || 0) * REM, marginRight: (col.mr || 0) * REM, marginLeft: (col.ml || 0) * REM,
    }}>
      {col.keys.map((pos) => (
        <KeyCap key={pos} pos={pos} data={kp.keysByPosition[pos]} mode={kp.mode}
          selected={kp.selectedPosition === pos} onSelectKey={kp.onSelectKey} layerMap={kp.layerMap} />
      ))}
    </div>
  );
}

function LedCol({ positions, keysByPosition, selectedPosition, onSelectKey }) {
  // Side (underglow) LEDs — narrow indicators like NayaFlow's LED view; the
  // 7-tall column is spaced to span the full height of the end key column.
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0.26 * REM, marginTop: 1.5 * REM, padding: "0 7px" }}>
      {positions.map((pos) => {
        const color = keysByPosition[pos]?.colorHex;
        return (
          <button key={pos} className={"kb-led" + (selectedPosition === pos ? " selected" : "")}
            title={`LED ${pos}`} onClick={() => onSelectKey(pos)}
            style={{ width: 1.2 * REM, height: 1.7 * REM, background: color || "var(--neutral20)" }} />
        );
      })}
    </div>
  );
}

function ModuleSlot({ id, pos, mode, moduleAssign, keysByPosition, selectedPosition, pickedModule, onAssignModule, onSelectModule, onSelectKey }) {
  if (mode === "color") {
    const color = keysByPosition[pos]?.colorHex;
    return (
      <button className={"kb-module color" + (selectedPosition === pos ? " selected" : "")}
        title={`${id} module LED`} onClick={() => onSelectKey(pos)} style={{ background: color || undefined }} />
    );
  }
  const assigned = moduleAssign[id];
  return (
    <button
      className={"kb-module" + (assigned ? " filled" : "") + ((assigned || onAssignModule) ? " clickable" : "") + (pickedModule ? " droptarget" : "")}
      title={assigned ? `${assigned} module — configure` : `${id} slot — drag or click-place a module`}
      onClick={() => { if (pickedModule && onAssignModule) onAssignModule(id, pickedModule); else if (assigned && onSelectModule) onSelectModule(assigned); }}
      onDragOver={(e) => { if (onAssignModule) e.preventDefault(); }}
      onDrop={(e) => { if (!onAssignModule) return; e.preventDefault(); const t = e.dataTransfer.getData("text/plain"); if (t) onAssignModule(id, t); }}
    >
      {assigned ? <img src={MODULE_IMG[assigned]} alt={assigned} className="kb-module-img" />
        : <><span className="kb-module-icon">◉</span><span className="kb-module-label">{id}</span></>}
    </button>
  );
}

export default function KeymapBoard(props) {
  const {
    keysByPosition = {}, mode = "bindings", selectedPosition = null, onSelectKey = () => {},
    onSelectModule = null, moduleAssign = {}, showModulePalette = false, onAssignModule = null,
    pickedModule = null, onPickModule = null, layerMap = {},
  } = props;
  const kp = { keysByPosition, mode, selectedPosition, onSelectKey, layerMap };

  return (
    <div className="keymap-board2">
      {mode === "color" && <LedCol positions={LEFT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}

      <div className="kb-half">
        {LEFT_COLS.map((col, i) => <Column key={i} col={col} align="start" {...kp} />)}
      </div>

      <div className="kb-center">
        {showModulePalette ? (
          <div className="kb-palette-row">
            {["track", "touch", "tune"].map((t) => (
              <img key={t} src={MODULE_IMG[t]} alt={t} draggable
                title={`Drag ${t} to a slot, or click then click a slot`}
                onDragStart={(e) => e.dataTransfer.setData("text/plain", t)}
                onClick={() => onPickModule && onPickModule(pickedModule === t ? null : t)}
                className={"kb-palette-mod" + (pickedModule === t ? " picked" : "")} />
            ))}
          </div>
        ) : (
          // No palette in Color mode — reserve its footprint so the slots still
          // land in the pocket (not shoved to the top by space-between).
          <div className="kb-palette-row kb-palette-spacer" aria-hidden="true" />
        )}
        <div className="kb-slots">
          <ModuleSlot id="left" pos={88} {...props} onSelectKey={onSelectKey} keysByPosition={keysByPosition} selectedPosition={selectedPosition} />
          <ModuleSlot id="right" pos={89} {...props} onSelectKey={onSelectKey} keysByPosition={keysByPosition} selectedPosition={selectedPosition} />
        </div>
        <div className="kb-thumbs">
          <div className="kb-thumb-group">{LEFT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} layerMap={layerMap} />)}</div>
          <div className="kb-thumb-group">{RIGHT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} layerMap={layerMap} />)}</div>
        </div>
      </div>

      <div className="kb-half">
        {RIGHT_COLS.map((col, i) => <Column key={i} col={col} align="end" {...kp} />)}
      </div>

      {mode === "color" && <LedCol positions={RIGHT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}
    </div>
  );
}
