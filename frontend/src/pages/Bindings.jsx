import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import FlashButton from "../components/FlashButton.jsx";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import useDoneFlag from "../lib/useDoneFlag";
import { readDockedModules } from "../lib/dockedModules";
import { setModuleRead, subscribeDeviceState, getDeviceState,
         deviceHasBeenRead } from "../lib/deviceState";
import { setShortcutTable } from "../lib/shortcutNames";
import { POS_LABEL } from "../lib/layout";
import { downloadJSON, pickJSONFile, pickProfileFile, safeName } from "../lib/files";
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
  // Show each key's LED colour as an outline on this page. Remembered, because it is a way of
  // working rather than a one-off view -- you turn it on while laying out a layer's colour
  // groups and want it still on when you come back.
  const [ledOutline, setLedOutline] = useState(() => {
    try { return localStorage.getItem("openflow.ledOutline") === "1"; } catch { return false; }
  });
  const [selectedPos, setSelectedPos] = useState(null);
  const [activeSlot, setActiveSlot] = useState("tap");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(null);
  const [readNote, setReadNote] = useState(null);
  const [justRead, markRead] = useDoneFlag();
  const [saved, setSaved] = useState(null);
  const [pickedModule, setPickedModule] = useState(null);
  const [moduleAssign, setModuleAssign] = useState(() => {
    // Only module types are valid here. A stray value -- a native image drag once wrote an
    // image URL into a bay -- persists in storage and renders as a broken image forever, so
    // it is discarded on read rather than trusted.
    const TYPES = ["track", "touch", "tune", "float"];
    const clean = (v) => (TYPES.includes(v) ? v : null);
    try {
      const saved = JSON.parse(localStorage.getItem("openflow.moduleAssign")) || {};
      return { left: clean(saved.left), right: clean(saved.right) };
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
      setShortcutTable(acts.shortcuts);
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
    const layerLabel = layer
      ? `Layer ${layer.orderId}${layer.name ? ` ${layer.name}` : ""}`
      : null;
    const liveIds = new Set(
      Object.values(deviceRead || {}).map((e) => e.matched).filter(Boolean));

    // Strictly what THIS profile has stored, falling back to the base layer for an unset bay.
    //
    // It deliberately does NOT re-resolve through the device read. Doing that made every
    // profile display whatever the board happened to be running, so a deliberate selection on
    // one profile silently showed as the live one instead -- the profile is a choice about
    // what to flash next, not a mirror of the keyboard. The read still marks which entries are
    // live; that is a label on the options, not a change to the answer.
    const selectedFor = (type, side) => {
      const own = layer?.bays?.[key(type, side)];
      if (own === "disabled") return "disabled";
      if (own && own !== "transparent") return own;
      const inh = base?.bays?.[key(type, side)];
      return inh && inh !== "transparent" ? inh : null;
    };

    return {
      layerLabel,
      // A Track profile belongs to one side: the left and right units are different hardware,
      // so the left bay must not offer right-hand profiles. Symmetric modules have a single
      // variant and every profile of the type is valid in either bay.
      profilesFor: (type, side) => {
        const t = type.toUpperCase();
        const want = t === "TRACK" && side ? `TRACK_${side.toUpperCase()}` : null;
        // A Track profile with NO side tag is offered in both bays. Imported profiles arrive
        // that way (a beta-era NayaFlow had one Track profile for both docks, 2026-09-11), and
        // the two stock side profiles differ only in button order, so nothing is unsafe about
        // it -- the wrong side just means the buttons come out mirrored.
        return (moduleProfiles || [])
          .filter((m) => m.type === t && (!want || !m.variant || m.variant === want))
          .map((m) => ({ id: m.id, name: m.name + (want && !m.variant ? " (no side set)" : ""),
                         onBoard: liveIds.has(m.id) }));
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
        const picked = await pickProfileFile();
        if (!picked) return;
        let firstId;
        if (picked.kind === "json") {
          const r = await api.importProfile(picked.data);
          firstId = r.id;
        } else {
          // a NayaFlow user-data.db or backup zip: converted server-side, each profile it
          // holds becomes a new profile here; the current data is never replaced
          const r = await api.importProfileFile(picked.file);
          firstId = r.imported?.[0]?.id;
        }
        await load();
        if (firstId) switchProfile(firstId);
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
    setReadNote(null);
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
      // A read that worked used to say nothing at all, so the only way to tell it apart from
      // a read that silently failed was to go looking at the data. The warning case went out
      // through setErr, which put a successful read behind an error-shaped message.
      markRead();
      setReadNote({
        at: new Date(),
        text: `${r.bindings} binding(s) across ${r.layers} layer(s)`,
        warnings: r.warnings?.length || 0,
      });
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
              <button
                className={"btn tiny led-toggle" + (ledOutline ? " primary" : "")}
                style={{ marginLeft: 10 }}
                aria-pressed={ledOutline}
                title={ledOutline
                  ? "Hide LED colours"
                  : "Outline each key in its LED colour, so you can see bindings and colour groups together"}
                onClick={() => {
                  const next = !ledOutline;
                  setLedOutline(next);
                  try { localStorage.setItem("openflow.ledOutline", next ? "1" : "0"); } catch { /* ignore */ }
                }}
              >
                ◌ LED colours
              </button>
            </div>
            <div className="board-actions-stack">
              {/* Above the buttons rather than beside them: as a sibling in the flex row a
                  note pushed every button left the moment a read finished. */}
              <div className="board-notes">
                {readNote && (
                  <span className={"saved-note" + (readNote.warnings ? "" : " ok")}>
                    Read {readNote.at.toLocaleTimeString()} — {readNote.text}
                    {readNote.warnings > 0 &&
                      ` · ${readNote.warnings} key(s) need review (BT/LED/other)`}
                  </span>
                )}
                {saved && (
                  <span className="saved-note">Backed up {saved.toLocaleTimeString()}</span>
                )}
              </div>
              <div className="board-actions">
                <button
                  className={"board-btn primary" + (justRead ? " btn-done" : "")}
                  onClick={readFromKeyboard}
                  disabled={!!busy}
                  title="Read the map currently on the connected keyboard into a new profile"
                >
                  {busy === "read" ? "Reading…" : justRead ? "✓ Read" : "⌨  Read from keyboard"}
                </button>
                <button className="board-btn" onClick={saveMap} disabled={!!busy}
                  title="Snapshot this profile to a backup file. Edits are saved as you make them —
  this is for keeping a restore point.">
                  {busy === "save" ? "Backing up…" : "⭳  Back up"}
                </button>
                <FlashButton variant="toolbar" />
              </div>
            </div>
          </div>
          <KeymapBoard
            keysByPosition={keysByPosition}
            mode="bindings"
            ledOutline={ledOutline}
            selectedPosition={selectedPos}
            onSelectKey={(pos) => { setSelectedPos(pos); setActiveSlot("tap"); }}
            layerMap={layerMap}
            names={catalog?.names || {}}
            moduleAssign={moduleAssign}
            showModulePalette
            onAssignModule={assignModule}
            pickedModule={pickedModule}
            onPickModule={setPickedModule}
            bays={bayUI}
            // Before the board has EVER been read, placing a module by hand is useful --
            // nothing else can know what is docked. After that it is not: a read replaces the
            // whole assignment. Gated on "ever read" rather than "currently known", because a
            // flash clears the detail and that would switch dragging back on after every one.
            allowModuleDrag={!deviceHasBeenRead()}
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
          names={catalog?.names || {}}
          activeSlot={activeSlot}
          onSelectSlot={setActiveSlot}
          onClearSlot={clearSlot}
          layerMap={layerMap}
        />
        <ActionPalette
          catalog={catalog}
          layers={profile.layers}
          currentLayerIndex={profile.layers.findIndex((l) => l.id === activeLayerId)}
          macros={macros}
          disabled={selectedPos == null}
          onPick={bind}
        />
      </div>
    </div>
  );
}
