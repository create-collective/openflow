import { useEffect, useRef, useState } from "react";
import WindowsIcon from "./WindowsIcon";
import { FUNCTION_ROW, MAIN_ROWS, NAV_ROWS, NUMPAD, VK_MODIFIERS, resolveVirtualKey, CODE_FOR_GLYPH } from "../lib/keydict";
import { LAYOUTS, LAYOUT_IDS } from "../lib/layouts";

// Keyboard units in px. 42 is a normal 1u key at the smallest the board is drawn; it grows with
// the width it is given (see the ResizeObserver below) up to 64. The three blocks are 22u wide
// plus the fixed gaps between them; the function row is sized to span exactly that.
const UNIT_MIN = 42;
const UNIT_MAX = 64;
const BLOCK_UNITS = 22;      // main 15u + nav 3u + numpad 4u
const BLOCK_GAPS_PX = 46;    // two 20px gaps between blocks, three 2px numpad grid gaps
const F_GAP_UNITS = 2;       // the gaps in the function row, in units

// The virtual keyboard tab: a full, realistically-proportioned board that flows from
// the canonical key dictionary. Select a key on the mapper, toggle any of the 5 held
// modifiers, then click a key here to bind it. Shift alone yields the shifted glyph
// (9 -> "("); any other modifier yields a shortcut_alias (C with Ctrl -> "LCTRL + C").
// `disabledHint` is threaded from the palette rather than hard-coded here: this component is
// shared with module gestures, where "select a key on the map" is the wrong instruction.
export default function VirtualKeyboard({ disabled, onPick,
                                          disabledHint = "Select a key on the map first." }) {
  const [mods, setMods] = useState({});
  const [unit, setUnit] = useState(UNIT_MIN);
  const root = useRef(null);
  const w = (u) => Math.max(0, u * unit - 2); // inner width; 2px goes to the 1px margins
  // The board fills the width it is given: a unit is what fits, between 42 and 64 px. The CSS
  // reads the same number (--vk-unit) for heights and type; the widths are inline already.
  useEffect(() => {
    const el = root.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const fit = () => {
      const u = Math.floor((el.clientWidth - BLOCK_GAPS_PX) / BLOCK_UNITS);
      setUnit(Math.min(UNIT_MAX, Math.max(UNIT_MIN, u)));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => { root.current?.style.setProperty("--vk-unit", unit + "px"); }, [unit]);
  const [mac, setMac] = useState(false);
  const [layout, setLayout] = useState(() => {
    try { return LAYOUTS[localStorage.getItem("openflow.vk.layout")] ? localStorage.getItem("openflow.vk.layout") : "qwerty"; }
    catch { return "qwerty"; }
  });
  const chooseLayout = (id) => {
    setLayout(id);
    try { localStorage.setItem("openflow.vk.layout", id); } catch { /* private mode: keep it in memory */ }
  };
  // Cosmetic relabel: show the layout's glyph, and bind the keycode that GLYPH names (so the "A"
  // key binds A wherever a layout draws it). A glyph with no US keycode -- an AZERTY accent --
  // has nothing to bind, so the key keeps its own code and the accent is display-only.
  const lay = (k) => {
    const o = LAYOUTS[layout].overrides[k.code];
    if (!o) return k;
    const shiftGlyph = o.s ?? (k.shift ? k.shift[1] : null);
    const shift = shiftGlyph == null ? null : [CODE_FOR_GLYPH[shiftGlyph] ?? (k.shift ? k.shift[0] : k.code), shiftGlyph];
    return { ...k, glyph: o.g, code: CODE_FOR_GLYPH[o.g] ?? k.code, shift };
  };
  const shift = !!mods.shift;
  const toggle = (id) => setMods((m) => ({ ...m, [id]: !m[id] }));
  const held = VK_MODIFIERS.filter((m) => mods[m.id]).map((m) => m.code);
  const click = (k) => { if (!disabled && k?.code) onPick(resolveVirtualKey(k.code, mods)); };
  // A key's secondary legend: its shifted symbol, or its Mac label — whichever it
  // has — and whether that legend is currently the active one.
  // LGUI/RGUI show the real Windows logo instead of the dictionary's maths glyph -- except in
  // mac mode, where altOf already swaps in the Cmd symbol.
  const glyphOf = (k) =>
    !mac && (k.code === "LGUI" || k.code === "RGUI") ? <WindowsIcon size={14} /> : k.glyph;
  const altOf = (k) => (k.shift ? { g: k.shift[1], on: shift } : (k.mac ? { g: k.mac, on: mac } : null));
  const macLabel = (m) => (mac ? ({ win: "Cmd", alt: "Option", altgr: "Option" }[m.id] || m.label) : m.label);

  const renderCell = (k, ci) => {
    if (!k) return <span key={ci} className="vk-gap" style={{ width: w(1) }} />;
    if (k.gap) return <span key={ci} className="vk-gap" style={{ width: w(k.u) }} />;
    k = lay(k);
    const alt = altOf(k);
    return (
      <button
        key={ci}
        className={"vk-key" + (alt && alt.on ? " shifted" : "")}
        style={{ width: w(k.u) }}
        disabled={disabled}
        title={shift && k.shift ? k.shift[0] : k.code}
        onClick={() => click(k)}
      >
        {alt && <span className="vk-sub">{alt.g}</span>}
        <span className="vk-base">{glyphOf(k)}</span>
      </button>
    );
  };

  // The function row spans the three blocks below it: Esc keeps its unit, the 24 F keys share
  // what is left. Through resolveVirtualKey like every other key, so "modifier + F13" works.
  const renderFunctionRow = () => {
    const fu = ((BLOCK_UNITS - 1 - F_GAP_UNITS) * unit + BLOCK_GAPS_PX) / 24 / unit;
    return (
      <div className="vk-row vk-frow">
        {FUNCTION_ROW.map((k, i) => renderCell(/^F[0-9]+$/.test(k.code || "") ? { ...k, u: fu } : k, i))}
      </div>
    );
  };

  const renderBlock = (rows, cls) => (
    <div className={"vk-block " + cls}>
      {rows.map((row, ri) => (
        <div className="vk-row" key={ri}>{row.map(renderCell)}</div>
      ))}
    </div>
  );

  const renderNumpad = () => (
    <div className="vk-block vk-numpad">
      {NUMPAD.map((k, i) => (
        <button
          key={i}
          className="vk-key vk-np-key"
          style={{ gridRow: `${k.row} / span ${k.rspan}`, gridColumn: `${k.col} / span ${k.cspan}` }}
          disabled={disabled}
          title={k.code}
          onClick={() => click(k)}
        >
          <span className="vk-base">{glyphOf(k)}</span>
        </button>
      ))}
    </div>
  );

  return (
    <div className="vk" ref={root}>
      {disabled && <div className="palette-disabled">{disabledHint}</div>}
      {renderFunctionRow()}
      <div className="vk-boards">
        {renderBlock(MAIN_ROWS, "vk-main")}
        {renderBlock(NAV_ROWS, "vk-nav")}
        {renderNumpad()}
      </div>
      <div className="vk-mods">
        <span className="vk-mods-label">Hold:</span>
        {VK_MODIFIERS.map((m) => (
          <label key={m.id} className={"vk-mod" + (mods[m.id] ? " on" : "")}>
            <input type="checkbox" checked={!!mods[m.id]} onChange={() => toggle(m.id)} />
            {macLabel(m)}
          </label>
        ))}
        <span className="vk-mods-sep" />
        <label className={"vk-mod" + (mac ? " on" : "")} title="Relabel modifiers as macOS (⌘ / ⌥) — the bindings are identical">
          <input type="checkbox" checked={mac} onChange={() => setMac((v) => !v)} />
          Mac
        </label>
        <span className="vk-mods-sep" />
        <label className="vk-mod vk-layout-pick" title="Relabel the virtual keyboard. Cosmetic only — a key still binds the keycode its label names.">
          Layout
          <select className="mac-input vk-layout-select" value={layout} onChange={(e) => chooseLayout(e.target.value)}>
            {LAYOUT_IDS.map((id) => <option key={id} value={id}>{LAYOUTS[id].label}</option>)}
          </select>
        </label>
        {/* Say what the next click will actually bind. Held modifiers DO build a chord, but
            nothing on screen said so -- they read as a display toggle, like Mac beside them --
            so there was no way to tell chording from relabelling without binding one and
            looking at the result. */}
        {held.length > 0 && (
          <span className="vk-combo-hint" title="The next key you pick will be bound as this chord">
            binds <code>{held.join(" + ")} + <span className="vk-combo-key">key</span></code>
          </span>
        )}
      </div>
    </div>
  );
}
