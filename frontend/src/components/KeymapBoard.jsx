import { keyLegend } from "../lib/keylabels";
import { SHAPES, POS_SHAPE } from "../lib/keyshapes";
import {
  LEFT_COLS, RIGHT_COLS, KEY_WRAPPERS, LEFT_THUMBS, RIGHT_THUMBS,
  LEFT_LEDS, RIGHT_LEDS, KEY_UNIT, REM,
} from "../lib/boardgeom";

const MODULE_IMG = { track: "/modules/track-plain.png", touch: "/modules/touch.png", tune: "/modules/tune.png" };

// One keycap: the exact NayaFlow SVG silhouette for its position, filled/stroked,
// with the resolved legend centered per-shape.
function KeyCap({ pos, data, mode, selected, onSelectKey }) {
  const shape = SHAPES[POS_SHAPE[pos]] || SHAPES.Ve;
  const [, , vbw, vbh] = shape.viewBox.split(" ").map(Number);
  const w = vbw * KEY_UNIT, h = vbh * KEY_UNIT;
  const legend = keyLegend(data?.binding);
  const color = data?.colorHex;
  const showColor = mode === "color" && color;
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
        // horizontal wrapper offsets as transform so they don't widen the column
        transform: (wrap.ml || wrap.mr)
          ? `translateX(${((wrap.ml || 0) - (wrap.mr || 0)) * REM}px)` : undefined,
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
      {mode !== "color" && (legend.main || legend.sub) && (
        <span className="kc-legend" style={{ top: shape.legend.top, left: shape.legend.left }}>
          {legend.sub && <span className="kc-sub">{legend.sub}</span>}
          <span className="kc-main">{legend.main}</span>
        </span>
      )}
    </button>
  );
}

function Column({ col, ...kp }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 0.1 * REM, alignItems: "center",
      marginTop: (col.mt || 0) * REM, marginRight: (col.mr || 0) * REM, marginLeft: (col.ml || 0) * REM,
    }}>
      {col.keys.map((pos) => (
        <KeyCap key={pos} pos={pos} data={kp.keysByPosition[pos]} mode={kp.mode}
          selected={kp.selectedPosition === pos} onSelectKey={kp.onSelectKey} />
      ))}
    </div>
  );
}

function LedCol({ positions, keysByPosition, selectedPosition, onSelectKey }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0.3 * REM, marginTop: 2.2 * REM, padding: "0 6px" }}>
      {positions.map((pos) => {
        const color = keysByPosition[pos]?.colorHex;
        return (
          <button key={pos} className={"kb-led" + (selectedPosition === pos ? " selected" : "")}
            title={`LED ${pos}`} onClick={() => onSelectKey(pos)}
            style={{ width: 1 * REM, height: 1.8 * REM, background: color || "var(--neutral20)" }} />
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
    pickedModule = null, onPickModule = null,
  } = props;
  const kp = { keysByPosition, mode, selectedPosition, onSelectKey };

  return (
    <div className="keymap-board2">
      {mode === "color" && <LedCol positions={LEFT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}

      <div className="kb-half">
        {LEFT_COLS.map((col, i) => <Column key={i} col={col} {...kp} />)}
      </div>

      <div className="kb-center">
        <div className="kb-center-modules">
          {showModulePalette && (
            <div className="kb-palette-row">
              {["track", "touch", "tune"].map((t) => (
                <img key={t} src={MODULE_IMG[t]} alt={t} draggable
                  title={`Drag ${t} to a slot, or click then click a slot`}
                  onDragStart={(e) => e.dataTransfer.setData("text/plain", t)}
                  onClick={() => onPickModule && onPickModule(pickedModule === t ? null : t)}
                  className={"kb-palette-mod" + (pickedModule === t ? " picked" : "")} />
              ))}
            </div>
          )}
          <div className="kb-slots">
            <ModuleSlot id="left" pos={88} {...props} onSelectKey={onSelectKey} keysByPosition={keysByPosition} selectedPosition={selectedPosition} />
            <ModuleSlot id="right" pos={89} {...props} onSelectKey={onSelectKey} keysByPosition={keysByPosition} selectedPosition={selectedPosition} />
          </div>
        </div>
        <div className="kb-thumbs">
          <div className="kb-thumb-group">{LEFT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} />)}</div>
          <div className="kb-thumb-group">{RIGHT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} />)}</div>
        </div>
      </div>

      <div className="kb-half">
        {RIGHT_COLS.map((col, i) => <Column key={i} col={col} {...kp} />)}
      </div>

      {mode === "color" && <LedCol positions={RIGHT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}
    </div>
  );
}
