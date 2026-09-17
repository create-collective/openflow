// Everything the Modules page knows and does, without a line of markup.
//
// The page used to hold seventeen pieces of state and every handler in one 980-line component.
// This hook owns the data (profiles, actions, catalog, variants, the device read), the selection
// (profile, tab, target, palette target), and every mutation, and hands the page and its
// components what they render. Behaviour is unchanged; only the seams moved.
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "./api";
import { confirmDialog } from "./dialogs";
import { subscribeDeviceState, getDeviceState } from "./deviceState";
import { useOnDeviceRead } from "./deviceActions";
import { downloadJSON, pickJSONFile, safeName } from "./files";
import { setShortcutTableFromActions } from "./shortcutNames";
import { axisHalfNames, byGesture, gestureName, makeLabelFor, okForKind, parseAxisHalfId } from "./moduleLabels";

export default function useModuleEditor() {
  const [modules, setModules] = useState([]);
  const [actions, setActions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState("bindings");
  const [activeTarget, setActiveTarget] = useState(null);
  const [err, setErr] = useState(null);
  // What is actually flashed on the keyboard, per module config (null = not read yet). Held
  // outside the component so it survives navigating to another page and back: a read costs a
  // COM-port round trip and is a whole-app fact, not this page's state.
  const device = useSyncExternalStore(subscribeDeviceState, getDeviceState).modules;
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(null);
  const [busy, setBusy] = useState(null);   // an axis edit in flight
  const [catalog, setCatalog] = useState(null);
  const [selectedBindingId, setSelectedBindingId] = useState(null);
  const [variants, setVariants] = useState([]);
  const [adding, setAdding] = useState(false);      // the "add profile" dropdown
  const [renaming, setRenaming] = useState(null);   // config id being renamed
  const [renameVal, setRenameVal] = useState("");
  const [searchParams] = useSearchParams();
  const wantType = (searchParams.get("type") || "").toUpperCase();
  // ?config= names one exact profile (a bay click, which knows which profile that bay runs);
  // ?type= is the looser fallback for when it does not.
  const wantConfig = searchParams.get("config") || "";

  async function load() {
    try {
      const r = await api.modules();
      const mods = r.modules || [];
      api.moduleVariants().then((v) => setVariants(v.variants || [])).catch(() => {});
      setModules(mods);
      setActions(r.actions || []);
      setShortcutTableFromActions(r.actions);
      if (!selectedId && mods.length) {
        // Prefer the exact profile the caller named, then a type match, then the first.
        const exact = wantConfig && mods.find((m) => m.id === wantConfig);
        const match = !exact && wantType && mods.find((m) => m.type === wantType);
        setSelectedId((exact || match || mods[0]).id);
      }
    } catch (e) {
      setErr(e.message);
    }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { api.actions().then(setCatalog).catch(() => {}); }, []);

  async function addProfile(variant) {
    setAdding(false);
    setErr(null);
    try {
      const r = await api.createModuleProfile(variant);
      await load();
      setSelectedId(r.id);
      setActiveTarget(null);
    } catch (e) {
      setErr(e.message);
    }
  }

  function startRename(m) {
    setRenaming(m.id);
    setRenameVal(m.name);
  }

  async function commitRename() {
    const id = renaming;
    const v = renameVal.trim();
    setRenaming(null);
    if (!id || !v) return;
    try {
      await api.renameModuleProfile(id, v);
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  async function removeProfile(m) {
    // The backend refuses the last profile of a type (a module with no profile cannot be
    // driven), so surface that reason rather than a bare failure.
    const ok = await confirmDialog({
      title: `Delete the module profile "${m.name}"?`,
      message: "Its bindings go with it.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    setErr(null);
    try {
      await api.deleteModuleProfile(m.id);
      if (selectedId === m.id) setSelectedId(null);
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  const config = modules.find((m) => m.id === selectedId) || null;

  const pairFor = (behavior) => (config?.pairs || []).find((p) => p.behavior === behavior);
  const pairForHalf = (behavior) =>
    (config?.pairs || []).find((p) => p.minusBehavior === behavior || p.plusBehavior === behavior);
  const isPairHalf = (behavior) => !!pairForHalf(behavior);

  async function toggleSplit(pair, combinedRow, on) {
    setBusy("split");
    try {
      const halves = (config.bindings || []).filter(
        (x) => x.behavior === pair.minusBehavior || x.behavior === pair.plusBehavior);
      if (on) {
        // Seed each half from the combined binding's matching side, so splitting starts from
        // what the gesture already did rather than from nothing.
        const parts = (combinedRow.actionCode || "").split(" - ").map((x) => x.trim());
        const seed = { [pair.minusBehavior]: parts.at(-2), [pair.plusBehavior]: parts.at(-1) };
        for (const h of halves) {
          await api.setModuleBinding({ bindingId: h.id, actionCode: seed[h.behavior] || "",
                                       actionType: seed[h.behavior] ? "key" : "none" });
        }
        await api.setModuleBinding({ bindingId: combinedRow.id, actionCode: "", actionType: "none" });
      } else {
        // Fold the halves back into the combined binding before clearing them. Blanking the
        // combined row on the way IN means there is nothing to restore on the way OUT, so the
        // value has to come back from the halves, which also preserves any edit made while
        // split was on.
        const by = Object.fromEntries(halves.map((h) => [h.behavior, h.actionCode || ""]));
        const minus = by[pair.minusBehavior], plus = by[pair.plusBehavior];
        const combined = minus || plus ? `${minus} - ${plus}` : "";
        await api.setModuleBinding({ bindingId: combinedRow.id, actionCode: combined,
                                     actionType: combined ? "value" : "none" });
        for (const h of halves) {
          await api.setModuleBinding({ bindingId: h.id, actionCode: "", actionType: "none" });
        }
      }
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(null); }
  }

  async function setAxisHalf(behavior, half, actionCode) {
    setBusy("axis");
    try {
      await api.setAxisSplit({ configId: selectedId, behavior, half, actionCode });
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(null); }
  }

  async function setAxisInvert(behavior, invert) {
    setBusy("axis");
    try {
      await api.setAxisInvert({ configId: selectedId, behavior, invert });
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(null); }
  }

  async function exportProfile(m) {
    setErr(null);
    try {
      // The document names its own module type, so a file can be imported anywhere without
      // the user having to remember which module it came from.
      const doc = await api.exportModuleProfile(m.id);
      downloadJSON(`${safeName(m.name)}.json`, doc);
      setImported({ at: new Date(), name: m.name, type: m.type,
                    bindings: Object.keys(doc.bindings || {}).length, skipped: 0,
                    verb: "Exported" });
    } catch (e) {
      setErr(`Could not export ${m.name}: ${e.message}`);
    }
  }

  async function importProfile() {
    setErr(null);
    let doc;
    try {
      doc = await pickJSONFile();
    } catch (e) {
      setErr(e.message);
      return;
    }
    if (!doc) return;                       // picker dismissed
    setImporting(true);
    try {
      // An import is always a NEW profile, never an overwrite, so importing the same file
      // twice leaves you two to compare rather than silently replacing what you had.
      const r = await api.importModuleProfile(doc);
      await load();
      setSelectedId(r.id);
      setImported({ at: new Date(), name: r.name, type: r.type, bindings: r.bindings,
                    skipped: (r.skipped || []).length });
    } catch (e) {
      setErr(`Could not import that file: ${e.message}`);
    } finally {
      setImporting(false);
    }
  }

  // A read (from the profile bar) publishes what the board carries into the shared device
  // state on its own; this page only has to notice when the read CAPTURED a profile the
  // board was running, because that has changed the list.
  useOnDeviceRead((r) => {
    if ((r.captured || []).length) return load();
    return undefined;
  });

  const grouped = useMemo(() => {
    const g = {};
    for (const m of modules) (g[m.type] ||= []).push(m);
    return g;
  }, [modules]);

  // An axis gesture is a direction PAIR, like the dial: one row until split, then two. Its
  // `split` from the server is derived from whether a half holds a key, so it cannot represent
  // "split, nothing bound yet", which is the state you are in the instant you tick the box.
  // Hence the open set is local, seeded from the server's view.
  const axisFor = (behavior) => (config?.axes || []).find((a) => a.behavior === behavior);
  // A pair row is one whether or not it holds a pair right now: an axis row (a Tune scroll, a
  // Track cursor) is a direction field, so once cleared it must still take only a pair, not
  // the keyboard. Split is how a single key gets onto one of its directions.
  const isPairRow = (sb) => sb.actionType === "value"
    || (sb.actionCode || "").includes(" - ")
    || (!sb.axisHalf && !!axisFor(sb.behavior));
  const [openAxes, setOpenAxes] = useState(() => new Set());
  useEffect(() => {
    setOpenAxes(new Set((config?.axes || []).filter((a) => a.split).map((a) => a.behavior)));
  }, [config]);

  function toggleAxisSplit(axis, on) {
    setOpenAxes((prev) => {
      const next = new Set(prev);
      if (on) next.add(axis.behavior); else next.delete(axis.behavior);
      return next;
    });
    // Closing it puts both directions back to motion. Nothing is stashed: the combined record
    // is rebuilt from the axis category and its direction signs.
    if (!on) {
      setAxisHalf(axis.behavior, "-", null);
      setAxisHalf(axis.behavior, "+", null);
    }
  }

  // A human name for whatever the palette is aimed at, including axis halves.
  const selectedTargetName = useMemo(() => {
    if (!selectedBindingId) return "";
    const half = parseAxisHalfId(selectedBindingId);
    if (half) {
      const [minusName, plusName] = axisHalfNames(half.behavior);
      const axis = axisFor(half.behavior);
      const base = gestureName(axis?.gesture || (half.behavior || "").split(":")[0]);
      return `${base} · ${half.side === "-" ? minusName : plusName}`;
    }
    const b = (config?.bindings || []).find((x) => x.id === selectedBindingId);
    return b ? gestureName(b.gesture) : "";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBindingId, config]);

  // The gesture row the palette is currently binding.
  const selectedBinding = useMemo(() => {
    const half = parseAxisHalfId(selectedBindingId);
    if (half) {
      // Both halves of every axis pair we have measured accept a keypress (the C7 probe wrote
      // one into the dial's field and it fired), so the palette is filtered as keypress.
      const axis = (config?.axes || []).find((a) => a.behavior === half.behavior);
      // With what it holds, so the strip can show it and offer to clear it. An empty half is
      // motion, not unassigned.
      return axis ? { axisHalf: half, fieldKind: "keypress",
                      actionCode: (half.side === "-" ? axis.minus : axis.plus) || "",
                      unsetText: "motion" } : null;
    }
    return (config?.bindings || []).find((b) => b.id === selectedBindingId) || null;
  }, [config, selectedBindingId]);

  // Only offer what this gesture's device field can actually hold. Without this the Extended
  // tab would show TRANSPARENT and BT_DEVICE_1 on a module gesture, neither of which it can
  // take. With nothing selected this must NOT reject everything: the palette drops categories
  // that filter empty and then tabs that lose all their categories, so a blanket false left it
  // with no tabs and it rendered nothing at all. "Nothing selected" is what `disabled` is for.
  // WHICH TABS, not just which actions: `filter` only reaches the grid tabs; the virtual
  // keyboard, the mouse and the app picker are custom render branches that never consult it.
  const paletteTabIds = useMemo(() => {
    if (!selectedBinding) return undefined;
    const isPair = isPairRow(selectedBinding);
    // Every direction pair we know lives in the module tab's Cursor/Scroll/Media categories,
    // and it is grid-rendered, so `filter` genuinely applies there.
    if (isPair) return ["module"];
    // A half takes a single key, or (since 2026-09-11) a single motion direction from the
    // mouse tab, which renders the eight directions instead of the pairs for a half.
    if (selectedBinding.axisHalf) return ["keyboard", "mouse", "basic", "extended", "shortcuts", "apps"];
    return undefined;
  }, [selectedBinding]);

  const labelFor = useMemo(() => makeLabelFor(actions), [actions]);

  const paletteFilter = useCallback(
    (a) => {
      if (!selectedBinding) return true;
      // A compound direction pair is two device fields with the sign as direction. Only
      // another pair can go there, and `fieldKind` is null on these rows so okForKind would
      // wave anything through, which is why the old dropdown offered all 101 actions for a
      // field that can hold five.
      const isPair = isPairRow(selectedBinding);
      if (isPair) return a.actionType === "value" || a.actionType === "none";
      // An axis HALF is one direction, so it takes a single action, never a pair.
      if (selectedBinding.axisHalf) return a.actionType !== "value";
      return okForKind(a.actionType, selectedBinding.fieldKind);
    },
    [selectedBinding]
  );

  async function pickFromPalette(pick) {
    if (!selectedBinding) return;
    // The catalog says none is DISABLE/"none"; module_bindings stores "" for unbound. Writing
    // the literal "DISABLE" would render as DISABLE and mean nothing to the flash encoder.
    const actionCode = pick.actionType === "none" ? "" : pick.actionCode;
    setBusy("bind");
    try {
      if (selectedBinding.axisHalf) {
        // A half is written through the axis endpoint: it is one direction of a field pair,
        // not a binding row, and clearing it returns that direction to motion rather than to
        // unbound.
        const { behavior, side } = selectedBinding.axisHalf;
        await api.setAxisSplit({ configId: selectedId, behavior, half: side,
                                 actionCode: actionCode || null });
      } else {
        await api.setModuleBinding({ bindingId: selectedBinding.id, actionCode,
                                     actionType: pick.actionType });
      }
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(null); }
  }

  // The strip and the selected row offer a clear: the gesture back to unbound (an axis half
  // back to motion), the same write as picking "none" from the palette.
  const clearSelected = () => pickFromPalette({ actionType: "none", actionCode: "" });

  // Which profile is LIVE is decided by the read's content match, not by sharing the device's
  // uuid: an edited-but-unflashed profile keeps the uuid while the board runs something else.
  const liveIds = useMemo(() => {
    const live = new Set();
    for (const e of Object.values(device || {})) if (e.matched) live.add(e.matched);
    return live;
  }, [device]);
  const isLive = (id) => liveIds.has(id);
  // The read entry describing the slot this profile occupies, live or not.
  const entryFor = (id) =>
    Object.values(device || {}).find((e) => e.matched === id || e.uuid === id) || null;
  const onDevice = config ? entryFor(config.id) : null;
  // One slot entry can describe two profiles (the drifted original and the capture taken from
  // the board), so the per-gesture rows differ by which one is selected. The entry's own rows
  // compare the board against the original; matchedGestures compares it against the capture.
  const isCapture = !!onDevice && onDevice.matched === config?.id && onDevice.uuid !== config?.id;
  const deviceGestures = isCapture ? (onDevice.matchedGestures || []) : (onDevice?.gestures || []);
  // Keyed by gesture AND by "gesture:half". An axis reports TWO rows under one gesture name,
  // so keying on the name alone let the plus half overwrite the minus half.
  const deviceByGesture = useMemo(() => {
    const g = {};
    for (const x of deviceGestures) {
      if (x.half) g[`${x.gesture}:${x.half}`] = x;
      else g[x.gesture] = x;
    }
    return g;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onDevice, isCapture]);

  // Every gesture with no button/finger target. A Tune axis is `vertical:tune:1_finger`, so it
  // HAS a target and renders there; a Track axis is `vertical:track` with no third segment, so
  // it lands here.
  const untargeted = useMemo(
    () => (config?.bindings || []).filter((b) => !b.target).sort(byGesture),
    [config]);
  const targets = useMemo(() => {
    const t = [];
    for (const b of config?.bindings || []) if (b.target && !t.includes(b.target)) t.push(b.target);
    return t.sort();
  }, [config]);
  const curTarget = activeTarget && targets.includes(activeTarget) ? activeTarget : targets[0];
  const targetBindings = (config?.bindings || [])
    .filter((b) => b.target === curTarget)
    .sort(byGesture);

  async function setSetting(fieldId, value) {
    if (!config) return;
    try {
      await api.setModuleSetting({ configId: config.id, fieldId, value });
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  function selectProfile(id) {
    setSelectedId(id);
    setActiveTarget(null);
    setSelectedBindingId(null);
  }

  return {
    // data
    modules, actions, catalog, variants, grouped, config, device, labelFor,
    // selection
    selectedId, selectProfile, tab, setTab, activeTarget, setActiveTarget, curTarget,
    selectedBindingId, setSelectedBindingId, selectedBinding, selectedTargetName,
    // per-config views
    untargeted, targets, targetBindings, onDevice, deviceByGesture, isLive, entryFor,
    pairFor, pairForHalf, isPairHalf, axisFor, openAxes,
    // status
    err, setErr, importing, imported, busy,
    // rail editing
    adding, setAdding, renaming, renameVal, setRenameVal, startRename, commitRename,
    cancelRename: () => setRenaming(null),
    // actions
    addProfile, removeProfile, exportProfile, importProfile,
    toggleSplit, toggleAxisSplit, setAxisInvert, setSetting,
    // palette
    paletteTabIds, paletteFilter, pickFromPalette, clearSelected,
  };
}
