import { useCallback, useEffect, useMemo, useState } from "react";
import FlashButton from "../components/FlashButton.jsx";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { POS_LABEL } from "../lib/layout";
import { downloadJSON, pickJSONFile, safeName } from "../lib/files";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import ProfileBar from "../components/ProfileBar";
import SelectedKeyPanel from "../components/SelectedKeyPanel";
import ActionPalette from "../components/ActionPalette";

export default function Bindings() {
  const [profiles, setProfiles] = useState([]);
  const [activeProfileId, setActiveProfileId] = useState(() => {
    try { return localStorage.getItem("openflow.activeProfile") || null; } catch { return null; }
  });
  const [catalog, setCatalog] = useState(null);
  const [macros, setMacros] = useState([]);
  const [activeLayerId, setActiveLayerId] = useState(null);
  const [selectedPos, setSelectedPos] = useState(null);
  const [activeSlot, setActiveSlot] = useState("tap");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(null);
  const [saved, setSaved] = useState(null);
  const [pickedModule, setPickedModule] = useState(null);
  const [moduleAssign, setModuleAssign] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("openflow.moduleAssign")) || { left: null, right: null };
    } catch {
      return { left: null, right: null };
    }
  });
  const navigate = useNavigate();

  function assignModule(slot, type) {
    setModuleAssign((prev) => {
      const next = { ...prev, [slot]: type };
      try { localStorage.setItem("openflow.moduleAssign", JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
    setPickedModule(null);
  }

  const load = useCallback(async () => {
    try {
      const [ud, acts, mac] = await Promise.all([api.userdata(), api.actions(), api.macros()]);
      setProfiles(ud.profiles || []);
      setCatalog(acts);
      setMacros(mac.macros || []);
    } catch (e) {
      setErr(e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const profile = useMemo(
    () => profiles.find((p) => p.id === activeProfileId) || profiles[0] || null,
    [profiles, activeProfileId]
  );

  // Keep an active layer that belongs to the active profile.
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

  const keysByPosition = useMemo(() => {
    const map = {};
    layer?.keys.forEach((k) => (map[k.positionId] = k));
    return map;
  }, [layer]);

  // layerId -> its index, so layer-switch keys can show "layers icon + number".
  const layerMap = useMemo(() => {
    const m = {};
    profile?.layers.forEach((l, i) => (m[l.id] = i));
    return m;
  }, [profile]);

  const selectedKey = selectedPos != null ? keysByPosition[selectedPos] : null;

  function persistProfile(id) {
    try { localStorage.setItem("openflow.activeProfile", id || ""); } catch { /* ignore */ }
  }
  function switchProfile(id) {
    setActiveProfileId(id);
    persistProfile(id);
    const p = profiles.find((x) => x.id === id);
    setActiveLayerId(p?.layers[0]?.id || null);
    setSelectedPos(null);
  }

  // --- profile handlers ---
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

  async function bind(pick) {
    if (selectedPos == null || !layer) return;
    try {
      await api.setKeyBinding({
        layerId: layer.id, positionId: selectedPos,
        actionCode: pick.actionCode, actionType: pick.actionType, behavior: activeSlot,
      });
      setSaved(null); // an edit means the map is no longer "saved" until Save is pressed
      await load();
    } catch (e) { setErr(e.message); }
  }

  async function clearSlot(slot) {
    if (selectedPos == null || !layer) return;
    try {
      await api.clearKeyBinding({ layerId: layer.id, positionId: selectedPos, behavior: slot });
      setSaved(null);
      await load();
    } catch (e) { setErr(e.message); }
  }

  async function readFromKeyboard() {
    setBusy("read");
    setErr(null);
    try {
      const r = await api.readKeyboard();
      await load();
      switchProfile(r.profileId);
      // Flashing is gated on this: until the board has been read, the app's idea of the keymap
      // may not match what is on the keyboard, and edits would be flashed over an unknown state.
      try { sessionStorage.setItem("openflow.deviceRead", String(Date.now())); } catch { /* ignore */ }
      if (r.warnings?.length) {
        setErr(`Read ${r.bindings} bindings across ${r.layers} layers — ${r.warnings.length} key(s) need review (BT/LED/other).`);
      }
    } catch (e) {
      const noDev = /device|found|503|connect/i.test(e.message);
      setErr(noDev ? "No keyboard found. Connect the Create over USB and close NayaFlow." : e.message);
    } finally {
      setBusy(null);
    }
  }

  async function saveMap() {
    setBusy("save");
    setErr(null);
    try {
      await api.createBackup();
      setSaved(new Date());
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!profile) {
    return (
      <div>
        <h1 className="page-title">Bindings</h1>
        <div className="card"><div className="empty">{err || "Loading keymap…"}</div></div>
      </div>
    );
  }

  return (
    <div className="editor">
      <div className="editor-top">
        <div className="layer-col">
          <ProfileBar profiles={profiles} activeProfileId={profile.id} {...profileHandlers} />
          <LayerList
            layers={profile.layers}
            activeLayerId={layer?.id}
            onSelect={(id) => { setActiveLayerId(id); setSelectedPos(null); }}
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
              <strong>{layer?.name}</strong>
            </div>
            <div className="board-actions">
              <button className="board-btn primary" onClick={readFromKeyboard} disabled={!!busy}
                title="Read the map currently on the connected keyboard into a new profile">
                {busy === "read" ? "Reading…" : "⌨  Read from keyboard"}
              </button>
              <button className="board-btn" onClick={saveMap} disabled={!!busy}
                title="Snapshot the current map to a backup">
                {busy === "save" ? "Saving…" : "Save"}
              </button>
              <FlashButton variant="toolbar" />
              {saved && <span className="saved-note">Saved {saved.toLocaleTimeString()}</span>}
            </div>
          </div>
          <KeymapBoard
            keysByPosition={keysByPosition}
            mode="bindings"
            selectedPosition={selectedPos}
            onSelectKey={(pos) => { setSelectedPos(pos); setActiveSlot("tap"); }}
            layerMap={layerMap}
            moduleAssign={moduleAssign}
            showModulePalette
            onAssignModule={assignModule}
            pickedModule={pickedModule}
            onPickModule={setPickedModule}
            onSelectModule={(type) => navigate(`/module-configuration?type=${type}`)}
          />
        </div>
      </div>

      {err && <div className="phase-note" style={{ margin: "8px 0" }}>{err}</div>}

      <div className="editor-bottom bindings-bottom">
        <SelectedKeyPanel
          label={selectedPos != null ? POS_LABEL[selectedPos] : null}
          bindings={selectedKey?.bindings || {}}
          slots={catalog?.behaviorSlots || []}
          activeSlot={activeSlot}
          onSelectSlot={setActiveSlot}
          onClearSlot={clearSlot}
          layerMap={layerMap}
        />
        <ActionPalette
          catalog={catalog}
          layers={profile.layers}
          macros={macros}
          disabled={selectedPos == null}
          onPick={bind}
        />
      </div>
    </div>
  );
}
