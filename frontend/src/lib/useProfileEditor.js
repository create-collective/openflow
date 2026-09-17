// The profile and layer plumbing Bindings and LED Map used to carry as two ~110-line copies:
// which profile is active, which layer, the layer's keys by position, and every profile and
// layer handler (new, rename, duplicate, delete, export, import; add, rename, duplicate, delete,
// reorder, set base, export, import, copy from another profile). One copy, on the shared
// profiles store and the shared active-profile store, so the pages and the persistent profile
// bar agree.
import { useEffect, useMemo, useState } from "react";
import { getActiveProfileId, setActiveProfileId, useActiveProfileId } from "./activeProfile";
import { api } from "./api";
import { downloadJSON, pickJSONFile, pickProfileFile, safeName } from "./files";
import { getProfiles, reloadProfiles, useProfiles } from "./profilesStore";

// Does this profile contain any layer-switch keys? If not, reordering cannot surprise anyone
// and the notice would just be noise.
const LAYER_PREFIXES = ["MO_LAYER_", "TO_LAYER_", "TOGGLE_LAYER_", "STICKY_LAYER_"];
export function countsSwitches(profile) {
  return (profile?.layers || []).some((l) =>
    (l.keys || []).some((k) =>
      LAYER_PREFIXES.some((p) => (k.binding?.actionCode || "").startsWith(p))));
}

export default function useProfileEditor({ onSwitch } = {}) {
  const { profiles, loaded, error: loadError } = useProfiles();
  const activeProfileId = useActiveProfileId();
  const [activeLayerId, setActiveLayerId] = useState(null);
  // Shown when a layer operation actually adjusted layer-switch keys, a change the user did
  // not type. Contextual rather than a standing caution: a permanent banner is dismissed once
  // and then never seen again, which is exactly when it would have mattered.
  const [layerNotice, setLayerNotice] = useState(null);
  const [err, setErr] = useState(null);

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

  // Reads the store directly rather than the render's `profiles`, so a switch right after a
  // reload (a read that produced a new profile) lands on the new list, not the stale closure.
  function switchProfile(id) {
    setActiveProfileId(id);
    const p = getProfiles().profiles.find((x) => x.id === id);
    setActiveLayerId(p?.layers[0]?.id || null);
    onSwitch?.(id);
  }

  const reload = reloadProfiles;

  const profileHandlers = {
    onSwitch: switchProfile,
    onNew: async () => {
      try { const r = await api.createProfile("New Profile"); await reload(); switchProfile(r.id); }
      catch (e) { setErr(e.message); }
    },
    onRename: async (id, name) => {
      try { await api.renameProfile(id, name); await reload(); }
      catch (e) { setErr(e.message); }
    },
    onDuplicate: async (id) => {
      try { const r = await api.duplicateProfile(id); await reload(); switchProfile(r.id); }
      catch (e) { setErr(e.message); }
    },
    onDelete: async (id) => {
      try { await api.deleteProfile(id); setActiveProfileId(null); await reload(); }
      catch (e) { setErr(e.message); }
    },
    onExport: async (id) => {
      try {
        const data = await api.exportProfile(id);
        downloadJSON(`${safeName(getProfiles().profiles.find((p) => p.id === id)?.name)}.openflow-profile.json`, data);
      } catch (e) { setErr(e.message); }
    },
    // A .json profile, or a NayaFlow user-data.db / backup zip: the latter is converted
    // server-side and each profile it holds becomes a new profile here; the current data is
    // never replaced. (LED Map used to accept only .json; both pages take both now.)
    onImport: async () => {
      try {
        const picked = await pickProfileFile();
        if (!picked) return;
        let firstId;
        if (picked.kind === "json") {
          const r = await api.importProfile(picked.data);
          firstId = r.id;
        } else {
          const r = await api.importProfileFile(picked.file);
          firstId = r.imported?.[0]?.id;
        }
        await reload();
        if (firstId) switchProfile(firstId);
      } catch (e) { setErr(e.message); }
    },
  };

  const layerHandlers = {
    onAdd: async (name) => {
      try { const r = await api.createLayer(profile.id, name); await reload(); setActiveLayerId(r.id); }
      catch (e) { setErr(e.message); }
    },
    onRename: async (id, name) => {
      try { await api.renameLayer(id, name); await reload(); }
      catch (e) { setErr(e.message); }
    },
    onDuplicate: async (id) => {
      try { await api.duplicateLayer(id); await reload(); }
      catch (e) { setErr(e.message); }
    },
    onDelete: async (id) => {
      try {
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
        await reload();
      } catch (e) { setErr(e.message); }
    },
    onReorder: async (orderedIds) => {
      try {
        await api.reorderLayers(profile.id, orderedIds);
        // No binding is rewritten: a switch holds the target layer's uuid and is resolved to
        // an index only at flash time, so it follows the layer it names. Worth saying anyway:
        // the layer's NUMBER changed, so a key the user thinks of as "go to layer 2" may now
        // read differently even though it still goes to the same layer.
        if (countsSwitches(profile)) {
          setLayerNotice(
            "Layer order changed. Switch keys still point at the layers they named, so "
            + "their numbers may have shifted. Check them before flashing.");
        }
        await reload();
      } catch (e) { setErr(e.message); }
    },
    onSetBase: async (id) => {
      try { await api.setBaseLayer(id); await reload(); }
      catch (e) { setErr(e.message); }
    },
  };

  const layerFileHandlers = {
    onExportLayer: async (id) => {
      try {
        const data = await api.exportLayer(id);
        const l = profile.layers.find((x) => x.id === id);
        downloadJSON(`${safeName(l?.name)}.openflow-layer.json`, data);
      } catch (e) { setErr(e.message); }
    },
    onCountReferences: (layerId) => api.layerReferences(layerId),
    // Copy a layer that already exists in the app, e.g. take the layer just read off the
    // keyboard and drop it into your own profile, without saving a file in between.
    onCopyLayerFrom: async (layerId) => {
      try {
        if (!profile) return;
        await api.copyLayer(layerId, profile.id);
        setLayerNotice(
          "Layer copied. Any switch keys on it were re-pointed at this profile's layer of the "
          + "same position. Check them before flashing.");
        await reload();
      } catch (e) { setErr(e.message); }
    },
    onImportLayer: async () => {
      try {
        const data = await pickJSONFile();
        if (!data || !profile) return;
        await api.importLayer(profile.id, data);
        await reload();
      } catch (e) { setErr(e.message); }
    },
  };

  return {
    profiles, loaded, error: err || loadError, setErr,
    activeProfileId: profile?.id || null, profile, layer, activeLayerId, setActiveLayerId,
    keysByPosition, layerMap, layerNotice, setLayerNotice,
    switchProfile, reload, profileHandlers, layerHandlers, layerFileHandlers,
  };
}

export { getActiveProfileId };
