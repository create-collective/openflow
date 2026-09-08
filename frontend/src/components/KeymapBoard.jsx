import { useState } from "react";
import ModuleBayPicker from "./ModuleBayPicker";
import { keyLegend } from "../lib/keylabels";
import { deviceColor } from "../lib/color";
import LayersIcon from "./LayersIcon";
import WindowsIcon from "./WindowsIcon";
import { SHAPES, POS_SHAPE } from "../lib/keyshapes";
import {
  LEFT_COLS, RIGHT_COLS, KEY_WRAPPERS, LEFT_THUMBS, RIGHT_THUMBS,
  LEFT_LEDS, RIGHT_LEDS, KEY_UNIT, REM,
} from "../lib/boardgeom";

// Track's left and right modules are physically different parts, not one module mirrored,
// so each gets its own artwork. Touch and Tune are symmetric and use a single image.
const MODULE_IMG = {
  track: { left: "/modules/track4-left.png", right: "/modules/track4-right.png" },
  touch: "/modules/touch.png",
  tune: "/modules/tune.png",
};

// `side` is the bay the module sits in, so a Track always renders the artwork for the
// half it is actually docked on rather than a fixed hand.
function moduleImg(type, side) {
  const entry = MODULE_IMG[type];
  if (!entry) return null;
  return typeof entry === "string" ? entry : entry[side] || entry.left;
}

// One palette entry per orderable part -- hence Track twice. Dropping still assigns a
// plain type; the bay decides which hand to draw, so a Track dragged from either entry
// looks right wherever it lands.
// `side` is the bay this entry governs, or null for a symmetric module that governs both.
// Track is the exception because its left and right units are different hardware.
const PALETTE = [
  { key: "track:left", type: "track", side: "left", art: "left", label: "Track (left)" },
  { key: "track:right", type: "track", side: "right", art: "right", label: "Track (right)" },
  { key: "touch", type: "touch", side: null, art: "left", label: "Touch" },
  { key: "tune", type: "tune", side: null, art: "left", label: "Tune" },
];
function paletteType(key) {
  return key ? String(key).split(":")[0] : key;
}

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
function KeyCap({ pos, data, mode, selected, onSelectKey, layerMap, ledOutline }) {
  const shape = SHAPES[POS_SHAPE[pos]] || SHAPES.Ve;
  const [, , vbw, vbh] = shape.viewBox.split(" ").map(Number);
  const w = vbw * KEY_UNIT, h = vbh * KEY_UNIT;
  const legend = keyLegend(data?.binding, layerMap);
  // A key can carry four behaviours (tap / hold / double-tap / tap+hold) in two records.
  // The legend only shows the tap, so mark the cap when there is more than one.
  const behaviours = data?.bindings ? Object.keys(data.bindings).length : 0;
  const code = data?.binding?.actionCode;
  // LGUI/RGUI get the real Windows logo rather than the maths glyph in the dictionary.
  const isWinKey = code === "LGUI" || code === "RGUI";
  const color = data?.colorHex;
  const showColor = mode === "color" && color;
  const textColor = showColor ? contrastText(color) : undefined;
  const fill = showColor ? color : "var(--neutral6)";
  // On Bindings, the LED colour can be shown as an OUTLINE rather than a fill. Filling the cap
  // (what the Colour page does) drowns out the legend, which is the whole point of this page --
  // you want to see the binding AND which colour group it is in at the same time. NayaFlow
  // outlines for the same reason.
  //
  // The colour shown is the DEVICE colour, matching the Colour page's board: what the keyboard
  // will actually light, not the picker value it came from.
  const led = ledOutline && mode !== "color" && color ? deviceColor(color) : null;
  // Selection still wins. A selected key must stay unambiguous, and an accent ring that some
  // keys replace with their own colour would make "which key am I editing" a guessing game.
  const stroke = selected ? "var(--accent)"
    : led ? led.hex
      : "var(--border-strong)";
  const strokeWidth = led && !selected ? 3.5 : 2;
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
            rx={shape.rect.rx} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        ) : (
          <path d={shape.d} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
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
          <span className="kc-main">{isWinKey ? <WindowsIcon size={15} /> : legend.main}</span>
        </span>
      )}
      {behaviours > 1 && (
        <span className="kc-multi" title={`${behaviours} behaviours: ${Object.keys(data.bindings).join(", ")}`}>
          ★
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
        <KeyCap key={pos} pos={pos} data={kp.keysByPosition[pos]} mode={kp.mode} ledOutline={kp.ledOutline}
          selected={kp.selectedPosition === pos} onSelectKey={kp.onSelectKey} layerMap={kp.layerMap} />
      ))}
    </div>
  );
}

function LedCol({ positions, keysByPosition, selectedPosition, onSelectKey }) {
  // Side (underglow) LEDs — narrow indicators like NayaFlow's LED view; the
  // 7-tall column is spaced to span the full height of the end key column.
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0.28 * REM, marginTop: 1.92 * REM, padding: "0 7px" }}>
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
      title={assigned ? `${assigned} module on the ${id} — open the profile this layer runs` : `${id} slot — drag or click-place a module`}
      onClick={() => { if (pickedModule && onAssignModule) onAssignModule(id, paletteType(pickedModule)); else if (assigned && onSelectModule) onSelectModule(assigned, id); }}
      onDragOver={(e) => {
        if (!onAssignModule) return;
        e.dataTransfer.dropEffect = "copy";
        e.preventDefault();
      }}
      onDrop={(e) => {
        if (!onAssignModule) return;
        e.preventDefault();
        // Only a known module type. A native image drag carries a URL, and accepting that put
        // "/modules/track4-right.png" into the bay, which then rendered as a broken image.
        const t = e.dataTransfer.getData("text/plain");
        if (t && Object.prototype.hasOwnProperty.call(MODULE_IMG, t)) onAssignModule(id, t);
      }}
    >
      {/* draggable={false} is load-bearing, not decoration. An <img> is a native drag source
          unless told otherwise, so this picture could start a drag carrying its own URL --
          which the drop handler then rejects, leaving Chrome with a drag it cannot finish, a
          stuck cursor and a page that swallows every click. The payload half of this was fixed
          before; the drag never should have started at all. */}
      {assigned ? <img src={moduleImg(assigned, id)} alt={assigned} className="kb-module-img"
                       draggable={false} />
        : <><span className="kb-module-icon">◉</span><span className="kb-module-label">{id}</span></>}
    </button>
  );
}

export default function KeymapBoard(props) {
  const {
    keysByPosition = {}, mode = "bindings", selectedPosition = null, onSelectKey = () => {},
    ledOutline = false,
    onSelectModule = null, moduleAssign = {}, showModulePalette = false, onAssignModule = null,
    pickedModule = null, onPickModule = null, layerMap = {}, bays = null,
    allowModuleDrag = true,
  } = props;
  const [openBay, setOpenBay] = useState(null);
  const kp = { keysByPosition, mode, selectedPosition, onSelectKey, layerMap, ledOutline };

  return (
    <div className="keymap-board2">
      {mode === "color" && <LedCol positions={LEFT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}

      <div className="kb-half">
        {LEFT_COLS.map((col, i) => <Column key={i} col={col} align="start" {...kp} />)}
      </div>

      <div className="kb-center">
        {showModulePalette ? (
          <div className="kb-palette-row">
            {PALETTE.map((m) => (
              <div className="kb-palette-slot" key={m.key}>
                <img src={moduleImg(m.type, m.art)} alt={m.label}
                  // Drag only matters BEFORE the board has been read. It writes the docked-module
                  // picture and nothing else -- not which profile the layer runs -- and a read
                  // overwrites the whole assignment from the device, so after one it is an action
                  // the next read silently undoes. Clicking (the profile picker) is the useful
                  // interaction either way.
                  draggable={allowModuleDrag}
                  title={allowModuleDrag
                    ? `${m.label} — drag onto a slot, or click to choose the profile this layer runs`
                    : `${m.label} — click to choose the profile this layer runs. The board shows what is actually docked, read from the keyboard.`}
                  // An <img> is draggable by default and a DEFAULT dragstart carries the image
                  // URL, which a bay once accepted as a module type. Setting the payload
                  // explicitly is what makes the drag safe, not disabling it.
                  //
                  // effectAllowed/dropEffect are set on BOTH ends deliberately. Left undefined,
                  // Chrome picks its own and the rejected-drop feedback can outlive the drag.
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = "copy";
                    e.dataTransfer.setData("text/plain", m.type);
                  }}
                  onDragEnd={(e) => { e.currentTarget.blur(); }}
                  onClick={() => setOpenBay(openBay === m.key ? null : m.key)}
                  className={"kb-palette-mod" + (openBay === m.key ? " picked" : "")} />
                {bays && (
                  <ModuleBayPicker
                    open={openBay === m.key}
                    anchorLabel={m.label}
                    layerLabel={bays.layerLabel}
                    profiles={bays.profilesFor(m.type, m.side)}
                    selectedId={bays.selectedFor(m.type, m.side)}
                    inherited={bays.inheritedFor(m.type, m.side)}
                    onPick={(id) => bays.onPick(m.type, m.side, id)}
                    onManage={() => bays.onManage(m.type, m.side)}
                    onClose={() => setOpenBay(null)} />
                )}
              </div>
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
          <div className="kb-thumb-group">{LEFT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} layerMap={layerMap} ledOutline={ledOutline} />)}</div>
          <div className="kb-thumb-group">{RIGHT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} layerMap={layerMap} ledOutline={ledOutline} />)}</div>
        </div>
      </div>

      <div className="kb-half">
        {RIGHT_COLS.map((col, i) => <Column key={i} col={col} align="end" {...kp} />)}
      </div>

      {mode === "color" && <LedCol positions={RIGHT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}
    </div>
  );
}
