import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { hsvToHex, isValidHex } from "../lib/color";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";

// Base swatches (recovered "Rainbow" palette + off). Users add custom colors.
const BASE_SWATCHES = [
  null, "#ff0000", "#ff6f00", "#ffe500", "#00ff00", "#00ffd9", "#0000ff", "#6f00ff", "#ffffff",
];
// ZMK-style RGB animations NayaFlow exposed.
const ANIMATIONS = [
  { id: null, label: "None" },
  { id: "solid", label: "Solid" },
  { id: "swirl", label: "Swirl" },
  { id: "breathe", label: "Breathe" },
  { id: "spectrum", label: "Spectrum" },
];
const TOOLS = [
  { id: "brush", label: "Brush", icon: "🖌" },
  { id: "fill", label: "Fill", icon: "🪣" },
  { id: "pipette", label: "Pipette", icon: "💧" },
];

export default function Color() {
  const [profile, setProfile] = useState(null);
  const [activeLayerId, setActiveLayerId] = useState(null);
  const [brush, setBrush] = useState("#00ff00");
  const [tool, setTool] = useState("brush");
  const [swatches, setSwatches] = useState(BASE_SWATCHES);
  const [err, setErr] = useState(null);
  // Custom color creator state
  const [showCreator, setShowCreator] = useState(false);
  const [hue, setHue] = useState(120);
  const [sat, setSat] = useState(100);
  const [hex, setHex] = useState("#00ff00");

  const load = useCallback(async () => {
    try {
      const ud = await api.userdata();
      const p = ud.profiles[0] || null;
      setProfile(p);
      if (p && p.layers[0]) setActiveLayerId((cur) => cur || p.layers[0].id);
    } catch (e) {
      setErr(e.message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const layer = useMemo(
    () => profile?.layers.find((l) => l.id === activeLayerId) || null,
    [profile, activeLayerId]
  );
  const keysByPosition = useMemo(() => {
    const map = {};
    layer?.keys.forEach((k) => (map[k.positionId] = k));
    return map;
  }, [layer]);

  async function onKey(positionId) {
    if (!activeLayerId) return;
    try {
      if (tool === "pipette") {
        const c = keysByPosition[positionId]?.colorHex;
        if (c) { setBrush(c); setHex(c); }
        return;
      }
      const color = tool === "fill" ? null : null; // set below
      const value = brush;
      if (tool === "fill") {
        await api.fillLayerColor({ layerId: activeLayerId, colorHex: value });
      } else {
        await api.setKeyColor({ layerId: activeLayerId, positionId, colorHex: value });
      }
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  function applyCreator(fromHsv) {
    const val = fromHsv ? hsvToHex(hue, sat) : hex;
    if (!isValidHex(val)) return;
    if (fromHsv) setHex(val);
    setBrush(val);
  }

  function addSwatch() {
    if (isValidHex(brush) && !swatches.includes(brush)) setSwatches([...swatches, brush]);
    setShowCreator(false);
  }

  async function setAnimation(anim) {
    if (!activeLayerId) return;
    await api.setLayerAnimation({ layerId: activeLayerId, animation: anim });
    await load();
  }

  if (!profile) {
    return <div><h1 className="page-title">Color</h1><div className="card"><div className="empty">{err || "Loading…"}</div></div></div>;
  }

  return (
    <div className="editor">
      <div className="editor-top">
        <LayerList
          profile={profile}
          layers={profile.layers}
          activeLayerId={activeLayerId}
          onSelect={(id) => setActiveLayerId(id)}
          onAdd={async (name) => { const r = await api.createLayer(profile.id, name); await load(); setActiveLayerId(r.id); }}
          onRename={async (id, name) => { await api.renameLayer(id, name); await load(); }}
          onDuplicate={async (id) => { await api.duplicateLayer(id); await load(); }}
          onDelete={async (id) => { await api.deleteLayer(id); if (activeLayerId === id) setActiveLayerId(null); await load(); }}
          onSetBase={async (id) => { await api.setBaseLayer(id); await load(); }}
        />
        <div className="board-wrap">
          <div className="board-header"><strong>{layer?.name}</strong> — LED view</div>
          <KeymapBoard keysByPosition={keysByPosition} mode="color" onSelectKey={onKey} />
        </div>
      </div>

      {err && <div className="phase-note" style={{ margin: "8px 0" }}>{err}</div>}

      <div className="editor-bottom" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div>
          <div className="card">
            <h3>LED Mapping Tools</h3>
            <div className="btn-row">
              {TOOLS.map((t) => (
                <button key={t.id} className={"btn" + (tool === t.id ? " primary" : "")} onClick={() => setTool(t.id)}>
                  {t.icon} {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>LED Color Palette</h3>
            <div className="swatches">
              {swatches.map((c, i) => (
                <button
                  key={i}
                  className={"swatch" + (brush === c ? " active" : "") + (c ? "" : " off")}
                  style={c ? { background: c } : undefined}
                  onClick={() => { setBrush(c); if (c) setHex(c); }}
                  title={c || "Off"}
                />
              ))}
              <button className="swatch add" title="Create color" onClick={() => setShowCreator((v) => !v)}>+</button>
            </div>

            {showCreator && (
              <div className="color-creator">
                <label>Hue: {hue}
                  <input type="range" min="0" max="360" value={hue}
                    onChange={(e) => { setHue(+e.target.value); }} onInput={() => applyCreator(true)} />
                </label>
                <label>Saturation: {sat}
                  <input type="range" min="0" max="100" value={sat}
                    onChange={(e) => { setSat(+e.target.value); }} onInput={() => applyCreator(true)} />
                </label>
                <div className="creator-row">
                  <div className="creator-preview" style={{ background: isValidHex(hex) ? hex : "#000" }} />
                  <input className="mac-input" value={hex}
                    onChange={(e) => setHex(e.target.value)}
                    onBlur={() => applyCreator(false)} />
                  <button className="btn" onClick={() => applyCreator(true)}>Use HSV</button>
                  <button className="btn primary" onClick={addSwatch}>Add swatch</button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <h3>Animations</h3>
          <p className="page-sub" style={{ marginBottom: 12 }}>Per-layer LED animation.</p>
          <div className="anim-list">
            {ANIMATIONS.map((a) => (
              <button
                key={a.id || "none"}
                className={"anim-item" + ((layer?.animationId || null) === a.id ? " active" : "")}
                onClick={() => setAnimation(a.id)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
