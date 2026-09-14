import { useState } from "react";
import WindowsIcon from "./WindowsIcon";
import { MAIN_ROWS, NAV_ROWS, NUMPAD, VK_MODIFIERS, FKEYS_EXTRA, resolveVirtualKey, CODE_FOR_GLYPH } from "../lib/keydict";
import { LAYOUTS, LAYOUT_IDS } from "../lib/layouts";

const UNIT = 42; // px per keyboard unit (a normal 1u key)
const w = (u) => Math.max(0, u * UNIT - 2); // inner width; 2px goes to the 1px margins

// The virtual keyboard tab: a full, realistically-proportioned board that flows from
// the canonical key dictionary. Select a key on the mapper, toggle any of the 5 held
// modifiers, then click a key here to bind it. Shift alone yields the shifted glyph
// (9 -> "("); any other modifier yields a shortcut_alias (C with Ctrl -> "LCTRL + C").
// `disabledHint` is threaded from the palette rather than hard-coded here: this component is
// shared with module gestures, where "select a key on the map" is the wrong instruction.
export default function VirtualKeyboard({ disabled, onPick,
                                          disabledHint = "Select a key on the map first." }) {
  const [mods, setMods] = useState({});
  const [fmore, setFmore] = useState(false);
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
  // Through resolveVirtualKey like every other key. It used to emit the bare F-key whatever
  // was held, and since F13-F24 live ONLY in this dropdown, "modifier + F13" was the one
  // combination the keyboard could not produce at all.
  const pickF = (code) => { setFmore(false); if (!disabled) onPick(resolveVirtualKey(code, mods)); };
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
    if (k.more === "fkeys") {
      return (

        <span key={ci} className="vk-fmore" style={{ width: w(k.u) }}>
          <button className="vk-key" disabled={disabled} title="More function keys (F13–F24)"
            onClick={() => setFmore((v) => !v)}>
            <span className="vk-base">F13▾</span>
          </button>
          {fmore && (
            <div className="vk-fmenu">
              {FKEYS_EXTRA.map((f) => (
                <button key={f} className="vk-fmenu-item" disabled={disabled} onClick={() => pickF(f)}>{f}</button>
              ))}
            </div>
          )}
        </span>
      );
    }
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
    <div className="vk">
      {disabled && <div className="palette-disabled">{disabledHint}</div>}
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
