import { useState } from "react";
import ModuleBayPicker from "./ModuleBayPicker";
import { keyLegend } from "../lib/keylabels";
import { ActionIcon, iconNameFor } from "../lib/icons";
import { deviceColor } from "../lib/color";
import LayersIcon from "./LayersIcon";
import WindowsIcon from "./WindowsIcon";
import { SHAPES, POS_SHAPE, badgeAnchor } from "../lib/keyshapes";
import {
  LEFT_COLS, RIGHT_COLS, KEY_WRAPPERS, LEFT_THUMBS, RIGHT_THUMBS,
  LEFT_LEDS, RIGHT_LEDS, KEY_UNIT, REM,
} from "../lib/boardgeom";

// Track's left and right modules are physically different PARTS. A Touch is one part, but
// it is not symmetric: docked in the left bay it presents the mirror of what it presents
// on the right, so it needs both images too. This comment used to claim Touch and Tune
// were both symmetric and shared one image, which is how a Touch on the left came to be
// drawn as a right-hand part (SCRUM-93). The Tune is a dial and genuinely is symmetric.
const MODULE_IMG = {
  track: { left: "/modules/v2/track-left.png", right: "/modules/v2/track-right.png" },
  touch: { left: "/modules/v2/touch-left.png", right: "/modules/v2/touch-right.png" },
  tune: "/modules/v2/tune.png",
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
  // `art` is which picture the PALETTE shows; the bay it lands in decides what gets drawn
  // there. Right-hand for the Touch so the picker looks exactly as it did before it had
  // two images to choose from.
  { key: "touch", type: "touch", side: null, art: "right", label: "Touch" },
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
  return lum > 0.6 ? "var(--text-on-light)" : "var(--text-on-dark)";
}

// A color bright enough to vanish against light mode's white caps (white, pale yellow, ...).
export function isLight(hex) {
  const n = parseInt(String(hex || "").replace("#", ""), 16);
  if (Number.isNaN(n)) return false;
  return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255 > 0.8;
}

// The cap's silhouette once, as a rect or a path, with whatever paint it is given.
function CapShape({ shape, ...paint }) {
  return shape.rect
    ? <rect x={shape.rect.x} y={shape.rect.y} width={shape.rect.w} height={shape.rect.h}
        rx={shape.rect.rx} {...paint} />
    : <path d={shape.d} {...paint} />;
}

// One keycap: the exact NayaFlow SVG silhouette for its position, filled/stroked,
// with the resolved legend centered per-shape.
function KeyCap({ pos, data, mode, selected, onSelectKey, layerMap, ledOutline, names }) {
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
  const fill = showColor ? color : "var(--bg-key)";
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
  // A light LED color (the spacebars set to white, say) disappears against light mode's white
  // caps and board, and the key loses its whole edge. Under such an outline goes a wider stroke
  // in --led-rim -- the key-border gray in light mode, transparent in dark -- so a thin rim of
  // gray shows on both sides of the white.
  const rim = led && !selected && isLight(led.hex) ? strokeWidth + 2 : 0;
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
        {rim > 0 ? (
          // Three layers so the gray shows on BOTH sides of the light outline: the cap's fill,
          // then the wider gray rim, then the LED color on top of it.
          <>
            <CapShape shape={shape} fill={fill} stroke="none" />
            <CapShape shape={shape} fill="none" stroke="var(--led-rim)" strokeWidth={rim} data-testid="led-rim" />
            <CapShape shape={shape} fill="none" stroke={stroke} strokeWidth={strokeWidth} />
          </>
        ) : (
          <CapShape shape={shape} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
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
          {(() => {
            // The cap draws NayaFlow's icon where the action has one; otherwise the text legend.
            const icon = !isWinKey && data?.binding && iconNameFor(data.binding.actionCode, names);
            return (
              <span className="kc-main">
                {isWinKey ? <WindowsIcon size={15} />
                  // Sized from the cap, not fixed: NayaFlow's glyphs are inset in their box, so
                  // two thirds of the cap's shorter side is what reads at a glance.
                  : icon ? <ActionIcon name={icon} size={Math.round(Math.min(w, h) * 0.68)} />
                  : legend.main}
              </span>
            );
          })()}
        </span>
      )}
      {behaviours > 1 && (
        // Anchored to the cap's own legend point, not the box's corner: the inner-column caps have
        // their bottom-left cut away, and a corner-pinned star sat outside the silhouette -- on
        // the neighbour, or on the module bay next to Backspace (SCRUM-111). See keyshapes.badgeAnchor.
        <span className="kc-multi" style={badgeAnchor(shape)}
          title={`${behaviours} behaviors: ${Object.keys(data.bindings).join(", ")}`}>
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
          selected={kp.selectedPosition === pos} onSelectKey={kp.onSelectKey} layerMap={kp.layerMap} names={kp.names} />
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
            style={{ width: 1.2 * REM, height: 1.7 * REM, background: color || "var(--led-off)" }} />
        );
      })}
    </div>
  );
}

function ModuleSlot({ id, pos, mode, moduleAssign, keysByPosition, selectedPosition, pickedModule, onAssignModule, onSelectModule, onSelectKey, moduleLed, onModuleLed }) {
  if (mode === "color") {
    // A bay's LEDs are a 24-wide BLOCK (88-111 left, 112-135 right), not the single position
    // this used to paint. `left` wrote LED 88 -- one of the left block's 24 -- and `right` wrote
    // LED 89, which is also in the LEFT block, so colouring the right module quietly changed the
    // left one's second LED. The block is stored per layer and per side; see
    // flash.MODULE_LED_BLOCKS.
    const color = moduleLed?.[id] || null;
    return (
      <button className={"kb-module color" + (color ? " set" : "")}
        title={color ? `${id} module LEDs: ${color}` : `${id} module LEDs — not set (keeps what the keyboard has)`}
        onClick={() => onModuleLed && onModuleLed(id)}
        style={{ background: color || undefined }} />
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
        // "/modules/track-right.png" into the bay, which then rendered as a broken image.
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
    ledOutline = false, moduleLed = null, onModuleLed = null,
    onSelectModule = null, moduleAssign = {}, showModulePalette = false, onAssignModule = null,
    pickedModule = null, onPickModule = null, layerMap = {}, bays = null,
    allowModuleDrag = true, names = {},
  } = props;
  const [openBay, setOpenBay] = useState(null);
  const kp = { keysByPosition, mode, selectedPosition, onSelectKey, layerMap, ledOutline, names };

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
          <ModuleSlot id="left" pos={88} {...props} onSelectKey={onSelectKey} keysByPosition={keysByPosition} selectedPosition={selectedPosition} moduleLed={moduleLed} onModuleLed={onModuleLed} />
          <ModuleSlot id="right" pos={89} {...props} onSelectKey={onSelectKey} keysByPosition={keysByPosition} selectedPosition={selectedPosition} moduleLed={moduleLed} onModuleLed={onModuleLed} />
        </div>
        <div className="kb-thumbs">
          <div className="kb-thumb-group">{LEFT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} layerMap={layerMap} ledOutline={ledOutline} names={names} />)}</div>
          <div className="kb-thumb-group">{RIGHT_THUMBS.map((pos) => <KeyCap key={pos} pos={pos} data={keysByPosition[pos]} mode={mode} selected={selectedPosition === pos} onSelectKey={onSelectKey} layerMap={layerMap} ledOutline={ledOutline} names={names} />)}</div>
        </div>
      </div>

      <div className="kb-half">
        {RIGHT_COLS.map((col, i) => <Column key={i} col={col} align="end" {...kp} />)}
      </div>

      {mode === "color" && <LedCol positions={RIGHT_LEDS} keysByPosition={keysByPosition} selectedPosition={selectedPosition} onSelectKey={onSelectKey} />}
    </div>
  );
}
