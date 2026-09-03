import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import FlashButton from "../components/FlashButton.jsx";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { readDockedModules } from "../lib/dockedModules";
import { setModuleRead, subscribeDeviceState, getDeviceState } from "../lib/deviceState";
import { POS_LABEL } from "../lib/layout";
import { downloadJSON, pickJSONFile, safeName } from "../lib/files";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import ProfileBar from "../components/ProfileBar";
import SelectedKeyPanel from "../components/SelectedKeyPanel";
import ActionPalette from "../components/ActionPalette";

// Does this profile contain any layer-switch keys? If not, reordering cannot surprise anyone
// and the notice would just be noise.
const LAYER_PREFIXES = ["MO_LAYER_", "TO_LAYER_", "TOGGLE_LAYER_", "STICKY_LAYER_"];
function countsSwitches(profile) {
  return (profile?.layers || []).some((l) =>
    (l.keys || []).some((k) =>
      LAYER_PREFIXES.some((p) => (k.binding?.actionCode || "").startsWith(p))));
}

export default function Bindings() {
  const [profiles, setProfiles] = useState([]);
  const [activeProfileId, setActiveProfileId] = useState(() => {
    try { return localStorage.getItem("openflow.activeProfile") || null; } catch { return null; }
  });
  // Shown when a layer operation actually adjusted layer-switch keys -- a change the user did
  // not type. Contextual rather than a standing caution: a permanent banner is dismissed once
  // and then never seen again, which is exactly when it would have mattered.
  const [layerNotice, setLayerNotice] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [moduleProfiles, setModuleProfiles] = useState([]);
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

  function persistAssign(patch) {
    setModuleAssign((prev) => {
      const next = { ...prev, ...patch };
      try { localStorage.setItem("openflow.moduleAssign", JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }

  function assignModule(slot, type) {
    persistAssign({ [slot]: type });
    setPickedModule(null);
  }

  const deviceRead = useSyncExternalStore(subscribeDeviceState, getDeviceState).modules;

  // Which module profile is running in one bay of the layer being edited.
  //
  // Three steps, and skipping any of them lands on the wrong profile: the layer's own bay
  // assignment, falling back to the BASE layer because an unset bay inherits from layer 0
  // (not from the nearest layer below -- proved by overriding a bay on layer 1 and pressing
  // the buttons on layer 2); then the device read, because the profile a bay names may be an
  // edited copy while the board is running the version we captured from it.
  function liveConfigForBay(type, bay) {
    if (!profile || !bay) return null;
    const layer = profile.layers.find((l) => l.id === activeLayerId);
    const base = profile.layers.find((l) => l.orderId === 0) || profile.layers[0];
    const key = `${type}:keyboard_${bay}`;
    let id = layer?.bays?.[key];
    if (!id || id === "transparent") id = base?.bays?.[key];
    if (!id || id === "transparent" || id === "disabled") return null;

    const entry = Object.values(deviceRead || {}).find((e) => e.uuid === id);
    return entry?.matched || id;
  }


  // Replace the hand-placed bays with what the board reports is actually docked. Best effort:
  // the keymap read has already succeeded by this point, so a module query that fails should
  // not turn a good read into an error.
  async function syncDockedModules() {
    try {
      persistAssign(await readDockedModules(api));
    } catch { /* leave the existing assignment alone */ }
  }

  const load = useCallback(async () => {
    try {
      const [ud, acts, mac, mods] = await Promise.all([
        api.userdata(), api.actions(), api.macros(), api.modules()]);
      setProfiles(ud.profiles || []);
      setCatalog(acts);
      setMacros(mac.macros || []);
      setModuleProfiles(mods.modules || []);
    } catch (e) {
      setErr(e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const profile = useMemo(
    () => profiles.find((p) => p.id === activeProfileId) || profiles[0] || null,
    [profiles, activeProfileId]
  );

  // Everything the board's module row needs to offer a profile per bay.
  //
  // A choice is written against the LAYER being edited. Set them on the base layer and the rest
  // inherit; change one elsewhere and only that layer differs -- the flash then works out that
  // the board needs the base layer's profiles plus that alternate.
  const bayUI = useMemo(() => {
    if (!profile || !catalog) return null;
    const layer = profile.layers.find((l) => l.id === activeLayerId);
    const base = profile.layers.find((l) => l.orderId === 0) || profile.layers[0];
    const key = (type, side) => `${type}:keyboard_${side || "left"}`;
    const liveIds = new Set(
      Object.values(deviceRead || {}).map((e) => e.matched).filter(Boolean));

    // The bay stores a uuid, but that uuid may name a profile that has drifted from the board.
    // Resolve it the same way the board's module click does -- through the read's content match
    // -- so the radio sits on the profile that is actually running, not on the row that merely
    // shares the device's identity.
    const resolveLive = (cid) => {
      if (!cid) return cid;
      const entry = Object.values(deviceRead || {}).find((e) => e.uuid === cid);
      return entry?.matched || cid;
    };

    const selectedFor = (type, side) => {
      const own = layer?.bays?.[key(type, side)];
      if (own === "disabled") return "disabled";
      if (own && own !== "transparent") return resolveLive(own);
      const inh = base?.bays?.[key(type, side)];
      return inh && inh !== "transparent" ? resolveLive(inh) : null;
    };

    return {
      // A Track profile belongs to one side: the left and right units are different hardware,
      // so the left bay must not offer right-hand profiles. Symmetric modules have a single
      // variant and every profile of the type is valid in either bay.
      profilesFor: (type, side) => {
        const t = type.toUpperCase();
        const want = t === "TRACK" && side ? `TRACK_${side.toUpperCase()}` : null;
        return (moduleProfiles || [])
          .filter((m) => m.type === t && (!want || m.variant === want))
          .map((m) => ({ id: m.id, name: m.name, onBoard: liveIds.has(m.id) }));
      },
      selectedFor,
      // True when this layer says nothing and the value shown comes from the base layer.
      inheritedFor: (type, side) => {
        if (!layer || layer.id === base?.id) return false;
        const own = layer.bays?.[key(type, side)];
        return !own || own === "transparent";
      },
      onPick: async (type, side, configId) => {
        try {
          await api.setLayerBay({
            layerId: activeLayerId, moduleType: type.toUpperCase(), side, configId,
          });
          await load();
        } catch (e) { setErr(e.message); }
      },
      onManage: (type, side) => {
        const id = selectedFor(type, side);
        navigate(id && id !== "disabled"
          ? `/module-configuration?config=${id}`
          : `/module-configuration?type=${type.toUpperCase()}`);
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, catalog, activeLayerId, deviceRead, moduleProfiles]);

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
    // Copy a layer that already exists in the app -- e.g. take the layer just read off the
    // keyboard and drop it into your own profile, without saving a file in between.
    onCountReferences: (layerId) => api.layerReferences(layerId),
    onCopyLayerFrom: async (layerId) => {
      try {
        if (!profile) return;
        await api.copyLayer(layerId, profile.id);
        setLayerNotice(
          "Layer copied. Any switch keys on it were re-pointed at this profile's layer of the "
          + "same position. Check them before flashing.");
        await load();
      } catch (e) { setErr(e.message); }
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
      await syncDockedModules();
      // A read is a read wherever it was started from: publish the module configs the board
      // carries into the shared device state, so the Modules page shows the on-device marks
      // without having to read again.
      if (r.modules) {
        const byUuid = {};
        for (const m of r.modules) byUuid[m.uuid] = m;
        setModuleRead(byUuid);
      }
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
            profiles={profiles.filter((p) => p.id !== profile.id)}
            layers={profile.layers}
            activeLayerId={layer?.id}
            onSelect={(id) => { setActiveLayerId(id); setSelectedPos(null); }}
            onAdd={async (name) => { const r = await api.createLayer(profile.id, name); await load(); setActiveLayerId(r.id); }}
            onRename={async (id, name) => { await api.renameLayer(id, name); await load(); }}
            onDuplicate={async (id) => { await api.duplicateLayer(id); await load(); }}
            onDelete={async (id) => {
              const r = await api.deleteLayer(id);
              if (activeLayerId === id) setActiveLayerId(null);
              const moved = (r?.repointedReferences || 0) + (r?.clearedReferences || 0);
              if (moved) {
                setLayerNotice(
                  r.repointedReferences
                    ? `${r.repointedReferences} layer-switch key(s) now point at the layer that took its place`
                      + (r.clearedReferences ? `, and ${r.clearedReferences} were cleared.` : ".")
                      + " Check them before flashing."
                    : `${r.clearedReferences} layer-switch key(s) were cleared — nothing took the deleted layer's place.`);
              }
              await load();
            }}
            onReorder={async (orderedIds) => {
              await api.reorderLayers(profile.id, orderedIds);
              // No binding is rewritten -- a switch holds the target layer's uuid and is
              // resolved to an index only at flash time, so it follows the layer it names.
              // Worth saying anyway: the layer's NUMBER changed, so a key the user thinks of
              // as "go to layer 2" may now read differently even though it still goes to the
              // same layer.
              if (countsSwitches(profile)) {
                setLayerNotice(
                  "Layer order changed. Switch keys still point at the layers they named, so "
                  + "their numbers may have shifted. Check them before flashing.");
              }
              await load();
            }}
            notice={layerNotice}
            onDismissNotice={() => setLayerNotice(null)}
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
            bays={bayUI}
            onSelectModule={(type, bay) => {
              const id = liveConfigForBay(type, bay);
              navigate(id ? `/module-configuration?config=${id}` : `/module-configuration?type=${type}`);
            }}
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
