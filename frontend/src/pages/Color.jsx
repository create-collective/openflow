import { useCallback, useEffect, useMemo, useState } from "react";
import FlashButton from "../components/FlashButton.jsx";
import { api } from "../lib/api";
import { hsvToHex, isValidHex } from "../lib/color";
import { downloadJSON, pickJSONFile, safeName } from "../lib/files";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import ProfileBar from "../components/ProfileBar";

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
  const [profiles, setProfiles] = useState([]);
  const [activeProfileId, setActiveProfileId] = useState(() => {
    try { return localStorage.getItem("openflow.activeProfile") || null; } catch { return null; }
  });
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
      setProfiles(ud.profiles || []);
    } catch (e) {
      setErr(e.message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const profile = useMemo(
    () => profiles.find((p) => p.id === activeProfileId) || profiles[0] || null,
    [profiles, activeProfileId]
  );

  useEffect(() => {
    if (!profile) return;
    if (!profile.layers.some((l) => l.id === activeLayerId)) {
      setActiveLayerId(profile.layers[0]?.id || null);
    }
  }, [profile, activeLayerId]);

  const layer = useMemo(
    () => profile?.layers.find((l) => l.id === activeLayerId) || profile?.layers[0] || null,
    [profile, activeLayerId]
  );

  function persistProfile(id) {
    try { localStorage.setItem("openflow.activeProfile", id || ""); } catch { /* ignore */ }
  }
  function switchProfile(id) {
    setActiveProfileId(id);
    persistProfile(id);
    const p = profiles.find((x) => x.id === id);
    setActiveLayerId(p?.layers[0]?.id || null);
  }
  const profileHandlers = {
    onSwitch: switchProfile,
    onNew: async () => { const r = await api.createProfile("New Profile"); await load(); switchProfile(r.id); },
    onRename: async (id, name) => { await api.renameProfile(id, name); await load(); },
    onDuplicate: async (id) => { const r = await api.duplicateProfile(id); await load(); switchProfile(r.id); },
    onDelete: async (id) => { await api.deleteProfile(id); persistProfile(null); setActiveProfileId(null); await load(); },
    onExport: async (id) => {
      const data = await api.exportProfile(id);
      downloadJSON(`${safeName(profiles.find((p) => p.id === id)?.name)}.openflow-profile.json`, data);
    },
    onImport: async () => {
      try {
        const data = await pickJSONFile();
        if (!data) return;
        const r = await api.importProfile(data);
        await load();
        switchProfile(r.id);
      } catch (e) { setErr(e.message); }
    },
  };
  const layerFileHandlers = {
    onExportLayer: async (id) => {
      const data = await api.exportLayer(id);
      const l = profile.layers.find((x) => x.id === id);
      downloadJSON(`${safeName(l?.name)}.openflow-layer.json`, data);
    },
    onImportLayer: async () => {
      try {
        const data = await pickJSONFile();
        if (!data || !profile) return;
        await api.importLayer(profile.id, data);
        await load();
      } catch (e) { setErr(e.message); }
    },
  };
  const keysByPosition = useMemo(() => {
    const map = {};
    layer?.keys.forEach((k) => (map[k.positionId] = k));
    return map;
  }, [layer]);

  // layerId -> index, so layer-switch keys show "layers icon + number" in the LED view too.
  const layerMap = useMemo(() => {
    const m = {};
    profile?.layers.forEach((l, i) => (m[l.id] = i));
    return m;
  }, [profile]);

  async function onKey(positionId) {
    if (!layer) return;
    try {
      if (tool === "pipette") {
        const c = keysByPosition[positionId]?.colorHex;
        if (c) { setBrush(c); setHex(c); }
        return;
      }
      const value = brush;
      if (tool === "fill") {
        await api.fillLayerColor({ layerId: layer.id, colorHex: value });
      } else {
        await api.setKeyColor({ layerId: layer.id, positionId, colorHex: value });
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
    if (!layer) return;
    await api.setLayerAnimation({ layerId: layer.id, animation: anim });
    await load();
  }

  if (!profile) {
    return <div><h1 className="page-title">LED Map</h1><div className="card"><div className="empty">{err || "Loading…"}</div></div></div>;
  }

  return (
    <div className="editor">
      <div className="editor-top">
        <div className="layer-col">
          <ProfileBar profiles={profiles} activeProfileId={profile.id} {...profileHandlers} />
          <LayerList
            layers={profile.layers}
            activeLayerId={layer?.id}
            onSelect={(id) => setActiveLayerId(id)}
            onAdd={async (name) => { const r = await api.createLayer(profile.id, name); await load(); setActiveLayerId(r.id); }}
            onRename={async (id, name) => { await api.renameLayer(id, name); await load(); }}
            onDuplicate={async (id) => { await api.duplicateLayer(id); await load(); }}
            onDelete={async (id) => { await api.deleteLayer(id); if (activeLayerId === id) setActiveLayerId(null); await load(); }}
            onSetBase={async (id) => { await api.setBaseLayer(id); await load(); }}
            {...layerFileHandlers}
          />
        </div>
        <div className="board-wrap">
          <div className="board-header">
            <div><strong>{layer?.name}</strong> — LED view</div>
            <div className="board-actions"><FlashButton variant="toolbar" /></div>
          </div>
          <KeymapBoard keysByPosition={keysByPosition} mode="color" onSelectKey={onKey} layerMap={layerMap} />
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
