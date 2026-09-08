import { useCallback, useEffect, useMemo, useState } from "react";
import FlashButton from "../components/FlashButton.jsx";
import { api } from "../lib/api";
import { hsvToHex, isValidHex, deviceColor } from "../lib/color";
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

  // What the BOARD will look like after a flash. The device stores hue + SATURATION and no
  // per-key brightness, so every fully-bright colour survives exactly and dark ones come back
  // at full brightness (#808080 -> white, #800000 -> red). keysByPosition is left alone so the
  // pipette picks up the colour the user chose, not the approximation.
  const boardKeys = useMemo(() => {
    const out = {};
    for (const [pos, k] of Object.entries(keysByPosition)) {
      const dev = deviceColor(k.colorHex);
      out[pos] = dev ? { ...k, colorHex: dev.hex } : k;
    }
    return out;
  }, [keysByPosition]);

  const brushDevice = deviceColor(brush);

  // Resolved once per swatch rather than three times per swatch per render -- and, more to the
  // point, `deviceColor` returns null for anything that is not a valid hex, so calling it inline
  // in both the title and the chip meant one bad swatch value would throw and blank the page.
  const swatchViews = useMemo(
    () => swatches.map((c) => ({ c, dev: deviceColor(c) })),
    [swatches]
  );

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
            <div>
              <strong>{layer?.name}</strong> — LED view
              <span className="page-sub" style={{ marginLeft: 8 }}>
                shown as the keyboard will light it
              </span>
            </div>
            <div className="board-actions"><FlashButton variant="toolbar" /></div>
          </div>
          <KeymapBoard keysByPosition={boardKeys} mode="color" onSelectKey={onKey} layerMap={layerMap} />
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
            <p className="page-sub" style={{ marginBottom: 10 }}>
              The keyboard stores a hue and a saturation — <strong>brightness is a keyboard-wide
              setting</strong>, not per key. So pale colours and white come out exactly as
              picked, while dark ones light up at full brightness. The board above shows the
              real result.
            </p>
            <div className="swatches">
              {swatchViews.map(({ c, dev }, i) => (
                <button
                  key={i}
                  className={"swatch" + (brush === c ? " active" : "") + (c ? "" : " off")}
                  style={c ? { background: c } : undefined}
                  onClick={() => { setBrush(c); if (c) setHex(c); }}
                  title={!c ? "Off" : dev && !dev.exact ? `${c} — lights up as ${dev.hex}` : c}
                >
                  {dev && !dev.exact && (
                    <span className="swatch-dev" style={{ background: dev.hex }} />
                  )}
                </button>
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
                  <div className="creator-preview" title="The colour you picked"
                    style={{ background: isValidHex(hex) ? hex : "#000" }} />
                  <span className="creator-arrow" aria-hidden="true">→</span>
                  <div className="creator-preview" title="How the keyboard will light it"
                    style={{ background: brushDevice ? brushDevice.hex : "#000" }} />
                  <input className="mac-input" value={hex}
                    onChange={(e) => setHex(e.target.value)}
                    onBlur={() => applyCreator(false)} />
                  <button className="btn" onClick={() => applyCreator(true)}>Use HSV</button>
                  <button className="btn primary" onClick={addSwatch}>Add swatch</button>
                </div>
                {brushDevice && (
                  <p className="page-sub" style={{ marginTop: 6 }}>
                    {brushDevice.exact
                      ? `The keyboard can show this exactly — hue ${brushDevice.hue}°, saturation ${brushDevice.saturation}%.`
                      : `Stored as hue ${brushDevice.hue}°, saturation ${brushDevice.saturation}% — the keyboard has no per-key brightness, so it will light up ${brushDevice.hex}.`}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <h3>
            Animations
            <span className="gesture-badge prov-experimental" style={{ marginLeft: 8 }}
              title="Stored in OpenFlow only. Nothing in the flash path sends an animation to the keyboard.">
              app only
            </span>
          </h3>
          {/* This card wrote layers.animation_id and nothing else. There is no reference to
              `animation` anywhere in device/, so picking one has never affected the keyboard --
              and unlike the other app-only features it carried no badge and no note at all.
              The capability is real but unwired: LED_SELECT_EFFECT (0x1011) and
              LED_EFFECT_CYCLE (0x100D) exist in constants.py with no caller, and NayaCore's
              strings carry LED_BREATHE / LED_SWIRL / Spectrum. It is also a LIVE effect rather
              than a stored per-layer property, so "per-layer" was wrong twice over. */}
          <p className="page-sub" style={{ marginBottom: 8 }}>
            Saved with the layer, but <strong>not sent to the keyboard</strong>. The board has an
            effect command we have not wired up yet, and it applies to the whole keyboard rather
            than to one layer — so this is a note to ourselves, not something the keys will do.
          </p>
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
