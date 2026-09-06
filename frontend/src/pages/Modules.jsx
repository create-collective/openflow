import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useSyncExternalStore } from "react";
import { subscribeDeviceState, getDeviceState, setModuleRead, deviceStateAt,
         deviceStateIsStored } from "../lib/deviceState";
import { useSearchParams } from "react-router-dom";
import ActionPalette from "../components/ActionPalette";
import { shortcutLabel, shortcutTooltip, shortcutInfo,
         setShortcutTableFromActions } from "../lib/shortcutNames";
import { api } from "../lib/api";
import { downloadJSON, pickJSONFile, safeName } from "../lib/files";
import useDoneFlag from "../lib/useDoneFlag";

// Module configuration (Touch / Track / Tune). Grouped list on the left; the
// selected config's bindings (module visual + always-on gestures + per-target
// tabs) and editable settings tabs in the center.

const TYPE_ORDER = ["TOUCH", "TRACK", "TUNE"];

// Canonical gesture order so Track Left / Right (and every config) list the same
// way — the DB returns them in inconsistent orders.
const GESTURE_ORDER = ["vertical", "horizontal", "rotate", "tap",
  "swipe_up", "swipe_down", "swipe_left", "swipe_right"];
const gi = (g) => {
  const i = GESTURE_ORDER.indexOf(g);
  return i === -1 ? 99 : i;
};
const byGesture = (a, b) => gi(a.gesture) - gi(b.gesture);

function cleanCode(code) {
  if (!code) return "—";
  // A known shortcut is shown by what it DOES, with the keys after it. Anything else falls back
  // to the stored code, tidied only enough to read.
  if (shortcutInfo(code)) return shortcutLabel(code, { withChord: true });
  return code.replaceAll(" - ", " / ").replaceAll("_", " ");
}
function targetLabel(t) {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// One editable gesture row: gesture label -> action dropdown. Options come from
// the backend catalog; an imported value that isn't in the catalog is kept as a
// synthetic first option so nothing is silently dropped.
// Action types each device field kind can actually hold (data-backed, mirrors the
// backend module_fields.action_ok_for_kind). Only these are offered when a gesture
// maps to a real device field, so the UI can't stage something the firmware refuses.
// A gesture field is not locked to one record type: the same field takes a keypress OR a
// mouse button, and the TYPE byte decides. Proven on hardware twice — Tune 0x08 took both,
// and NayaFlow wrote KEYPRESS records into the Track button fields that normally hold masks.
const CLICK_TYPES = new Set(["key", "modifier", "shortcut_alias", "mouse"]);
function okForKind(actionType, fieldKind) {
  if (actionType === "none") return true;
  if (fieldKind === "keypress" || fieldKind === "mouse_button") return CLICK_TYPES.has(actionType);
  if (fieldKind === "axis") return actionType === "value";
  return true; // no device field (DB-only) — don't restrict, but the row is badged
}

// Behaviors whose slug does not read as a name. Pinch and spread are ONE gesture on this
// hardware -- a single "pinch + tap" -- so it is one row, not two.
const GESTURE_LABEL = { pinch: "Pinch & Spread" };

function GestureRow({ b, actions, onPick, dev, extra, selected, onSelect }) {
  // Constrain the dropdown to what this gesture's device field accepts.
  const usable = actions.filter((a) => okForKind(a.actionType, b.fieldKind));
  const known = usable.some((a) => a.code === (b.actionCode || ""));
  const opts = known
    ? usable
    : [{ code: b.actionCode || "", label: cleanCode(b.actionCode), actionType: b.actionType, group: "Imported" }, ...usable];
  // Group into <optgroup>s (blank group renders ungrouped at the top).
  const order = [];
  const groups = {};
  for (const o of opts) {
    const g = o.group || "";
    if (!(g in groups)) { groups[g] = []; order.push(g); }
    groups[g].push(o);
  }
  // A Track hold has no device field at all: the capture showed NayaFlow writing the hold value
  // over the tap and the tap never reaching the board. Offering it as editable would be
  // offering to lose the tap, so it renders disabled.
  // A Track hold has no device field at all. A split parent is different: it is supported,
  // its value simply lives on the two half rows -- so it is disabled but must not wear the
  // "experimental" badge, which is specifically about a binding the hardware cannot store.
  const unsupported = /^hold:track:button_/.test(b.behavior || "");
  const splitParent = !!b.pairedSplit;
  const badge = unsupported
    ? { cls: "dbonly", text: "experimental", title: "The Track has one field per button and no room for a hold. NayaFlow lets you set one and silently overwrites the tap; we do not." }
    : b.flashable
    ? { cls: "flashable", text: "flashable", title: "This gesture is stored on the device and can be flashed." }
    // There used to be an "axis" rung here, reading "writing this is not confirmed yet". It
    // dated from before axis writing WAS confirmed -- it has since been flashed and read back
    // on hardware -- so it only ever fired when something else was wrong, and told the user
    // about a field kind rather than about whether their edit reaches the keyboard. Which is
    // the only thing the badge is for; `fieldKind` still earns its keep filtering the palette.
    : { cls: "dbonly", text: "app only", title: "No device field for this gesture yet — edits stay in the app until confirmed." };
  return (
    <div
      className={"skp-row" + (selected ? " selected" : "")}
      style={onSelect ? undefined : { cursor: "default" }}
      onClick={onSelect ? () => onSelect(b.id) : undefined}
    >
      <span className="skp-beh" style={{ textTransform: GESTURE_LABEL[b.gesture] ? "none" : "capitalize" }}>
        {GESTURE_LABEL[b.gesture] || (b.gesture || "").replace(/_/g, " ")}
      </span>
      <span className={"gesture-badge " + badge.cls} title={badge.title}>{badge.text}</span>
      {dev && (
        <span
          className={"gesture-badge " + (dev.differs ? "dbonly" : "flashable")}
          title={dev.differs
            ? `On the keyboard this is ${dev.device ?? "unbound"}; the app has ${dev.app || "nothing"}. Flash to make them match.`
            : `Matches what is on the keyboard (field ${"0x" + dev.field.toString(16)}).`}
        >
          {dev.differs ? `device: ${dev.device ?? "unbound"}` : "on device"}
        </span>
      )}
      <span className="skp-arrow" title={shortcutTooltip(b.actionCode)}>→</span>
      <select
        className="mac-input mod-action"
        value={b.actionCode || ""}
        // A split parent is disabled too: its value lives on the half rows below, so editing it
        // here would fight them.
        disabled={unsupported || splitParent}
        // One title, resolved in priority order. Two `title` attributes silently kept only the
        // last, so the shortcut tooltip was dead on every row.
        title={
          splitParent
            ? "Split is on — each direction is set separately below. Untick split to give the whole gesture one action."
            : unsupported
            ? "The Track cannot store a hold — setting one would overwrite the tap."
            : shortcutInfo(b.actionCode)
            ? shortcutTooltip(b.actionCode)
            : undefined
        }
        onChange={(e) => onPick(b.id, opts.find((o) => o.code === e.target.value))}
      >
        {order.map((g) =>
          g ? (
            <optgroup key={g} label={g}>
              {groups[g].map((o) => <option key={o.code || "none"} value={o.code}>{o.label}</option>)}
            </optgroup>
          ) : (
            groups[g].map((o) => <option key={o.code || "none"} value={o.code}>{o.label}</option>)
          )
        )}
      </select>
      {extra}
    </div>
  );
}

// Module display images (from ScreenshotsOfNayaFlow/pngs, centers made
// transparent). Track swaps image by the active button to highlight it.
function ModuleVisual({ type, activeButton }) {
  let src;
  if (type === "TRACK") {
    const m = /button_(\d)/.exec(activeButton || "");
    src = `/modules/track${m ? m[1] : "1"}.png`;
  } else if (type === "TUNE") {
    src = "/modules/tune.png";
  } else {
    src = "/modules/touch.png";
  }
  return (
    <div className="mod-visual">
      <img src={src} alt={`${type} module`} className="mod-img" />
    </div>
  );
}

export default function Modules() {
  const [modules, setModules] = useState([]);
  const [actions, setActions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState("bindings");
  const [activeTarget, setActiveTarget] = useState(null);
  const [err, setErr] = useState(null);
  // What is actually flashed on the keyboard, per module config (null = not read yet).
  // Held outside the component so it survives navigating to another page and back -- a read
  // costs a COM-port round trip and is a whole-app fact, not this page's state.
  const device = useSyncExternalStore(subscribeDeviceState, getDeviceState).modules;
  const [reading, setReading] = useState(false);
  const [readNote, setReadNote] = useState(null);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(null);
  const [justRead, markRead] = useDoneFlag();
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

  // Read the module configs off the keyboard and diff them against the app. Read-only:
  // the app has always shown only its own stored bindings, so until this runs there is no
  // way to tell an edit that was flashed from one that was never written.
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
    // The backend refuses the last profile of a type -- a module with no profile cannot be
    // driven -- so surface that reason rather than a bare failure.
    if (!window.confirm(`Delete the module profile "${m.name}"? Its bindings go with it.`)) return;
    setErr(null);
    try {
      await api.deleteModuleProfile(m.id);
      if (selectedId === m.id) setSelectedId(null);
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

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
        // value has to come back from the halves -- which also preserves any edit made while
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
      // An import is always a NEW profile -- never an overwrite -- so importing the same file
      // twice leaves you two to compare rather than silently replacing what you had.
      const r = await api.importModuleProfile(doc);
      await load();
      setSelectedId(r.id);
      setReadNote(null);
      setImported({ at: new Date(), name: r.name, type: r.type, bindings: r.bindings,
                    skipped: (r.skipped || []).length });
    } catch (e) {
      setErr(`Could not import that file: ${e.message}`);
    } finally {
      setImporting(false);
    }
  }

  async function readDevice() {
    setReading(true);
    setErr(null);
    setReadNote(null);
    try {
      const r = await api.readModules();
      const byUuid = {};
      for (const m of r.modules || []) byUuid[m.uuid] = m;
      setModuleRead(byUuid);
      // A read that captures a profile has CHANGED the profile list, and one that finds the
      // board unchanged has not -- both used to look identical, which is to say like nothing
      // had happened at all.
      const captured = (r.captured || []).length;
      if (captured) await load();
      markRead();
      setReadNote({
        at: new Date(),
        slots: (r.modules || []).filter((m) => !m.unknown).length,
        captured,
      });
    } catch (e) {
      setErr(`Could not read the keyboard: ${e.message}`);
    } finally {
      setReading(false);
    }
  }

  const grouped = useMemo(() => {
    const g = {};
    for (const m of modules) (g[m.type] ||= []).push(m);
    return g;
  }, [modules]);

  const config = modules.find((m) => m.id === selectedId) || null;

  // An axis gesture is a direction PAIR, like the dial -- one row until split, then two.
  // Its `split` from the server is derived from whether a half holds a key, so it cannot
  // represent "split, nothing bound yet", which is the state you are in the instant you tick
  // the box. Hence the open set is local, seeded from the server's view.
  const axisFor = (behavior) => (config?.axes || []).find((a) => a.behavior === behavior);
  // An axis half is addressed by behavior + direction rather than by a binding id, so it needs a
  // selection id of its own to be a palette target.
  const axisHalfId = (behavior, side) => `axis:${behavior}:${side}`;
  const parseAxisHalfId = (id) => {
    if (typeof id !== "string" || !id.startsWith("axis:")) return null;
    const side = id.slice(-1);
    return { behavior: id.slice(5, -2), side };
  };
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

  const AXIS_HALF_LABEL = {
    vertical: ["Up", "Down"], horizontal: ["Left", "Right"],
    rotate: ["Rotate left", "Rotate right"],
  };

  function axisHalfRows(axis) {
    const head = (axis.behavior || "").split(":")[0];
    const [minusName, plusName] = AXIS_HALF_LABEL[head] || ["–", "+"];
    const keyActions = actions.filter((a) => a.actionType === "key" || a.actionType === "keypress");
    // With invert on, name the direction the half NOW drives rather than a stale label.
    const motionOf = (side) => {
      const d = side === "-" ? axis.defaultMinus : axis.defaultPlus;
      const eff = axis.invert ? (side === "-" ? axis.defaultPlus : axis.defaultMinus) : d;
      return (eff || "").replace(/_/g, " ").toLowerCase();
    };
    return ["-", "+"].map((side) => {
      // A half is not a binding row, so it has no binding id -- it is addressed by behavior and
      // direction. Give it a synthetic selection id so the palette can target it like any other
      // row, and let the dropdown stay as the quick path.
      const selId = axisHalfId(axis.behavior, side);
      const code = side === "-" ? axis.minus : axis.plus;
      return (
        <div className={"skp-row" + (selectedBindingId === selId ? " selected" : "")}
          key={axis.behavior + side}
          onClick={() => setSelectedBindingId(selId)}>
          <span className="skp-beh" style={{ textTransform: "none", paddingLeft: 18 }}>
            {side === "-" ? minusName : plusName}
          </span>
          <span className="skp-arrow">→</span>
          <select className="mac-input mod-action"
            value={code || ""}
            disabled={!!busy}
            title={`device field 0x${axis.fields[side].toString(16).padStart(2, "0")}`}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setAxisHalf(axis.behavior, side, e.target.value || null)}>
            <option value="">{motionOf(side) ? `motion — ${motionOf(side)}` : "motion"}</option>
            {code && !keyActions.some((a) => a.code === code) && (
              // Bound from the palette to something outside the module vocabulary. Without
              // this the select has no matching option, silently falls back to showing its
              // FIRST entry, and a save that worked reads as one that did nothing.
              <option value={code}>{cleanCode(code)}</option>
            )}
            {keyActions.map((a) => <option key={a.code} value={a.code}>{a.label || a.code}</option>)}
          </select>
        </div>
      );
    });
  }

  // The gesture row the palette is currently binding.
  const selectedBinding = useMemo(() => {
    const half = parseAxisHalfId(selectedBindingId);
    if (half) {
      // Both halves of every axis pair we have measured accept a keypress -- the C7 probe wrote
      // one into the dial's field and it fired -- so the palette is filtered as keypress.
      const axis = (config?.axes || []).find((a) => a.behavior === half.behavior);
      return axis ? { axisHalf: half, fieldKind: "keypress" } : null;
    }
    return (config?.bindings || []).find((b) => b.id === selectedBindingId) || null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, selectedBindingId]);

  // Only offer what this gesture's device field can actually hold. Without this the Extended tab
  // would show TRANSPARENT and BT_DEVICE_1 on a module gesture, neither of which it can take.
  // With nothing selected this must NOT reject everything: the palette drops categories that
  // filter empty and then tabs that lose all their categories, so a blanket false left it with
  // no tabs and it rendered nothing at all. "Nothing selected" is what `disabled` is for.
  const paletteFilter = useCallback(
    (a) => !selectedBinding || okForKind(a.actionType, selectedBinding.fieldKind),
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
        // A half is written through the axis endpoint: it is one direction of a field pair, not
        // a binding row, and clearing it returns that direction to motion rather than to unbound.
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
  // One slot entry can describe two profiles -- the drifted original and the capture taken from
  // the board -- so the per-gesture rows differ by which one is selected. The entry's own rows
  // compare the board against the original; matchedGestures compares it against the capture.
  const isCapture = !!onDevice && onDevice.matched === config?.id && onDevice.uuid !== config?.id;
  const deviceGestures = isCapture ? (onDevice.matchedGestures || []) : (onDevice?.gestures || []);
  const deviceByGesture = useMemo(() => {
    const g = {};
    for (const x of deviceGestures) g[x.gesture] = x;
    return g;
  }, [onDevice, isCapture]);

  // Every gesture with no button/finger target. These used to exclude anything in
  // `config.axes`, on the grounds that "the axes have their own two-direction control above" --
  // true when AxisControls existed, and silently wrong after it was deleted and the axis rows
  // moved into the target tabs. A Tune axis is `vertical:tune:1_finger`, so it HAS a target and
  // renders there; a Track axis is `vertical:track` with no third segment, so it had no target
  // and was excluded from here as well. The Track's vertical, horizontal and rotate rows
  // rendered nowhere at all.
  const untargeted = useMemo(
    () => (config?.bindings || []).filter((b) => !b.target).sort(byGesture),
    [config]);
  const targets = useMemo(() => {
    const t = [];
    for (const b of config?.bindings || []) if (b.target && !t.includes(b.target)) t.push(b.target);
    return t.sort();
  }, [config]);
  const curTarget = activeTarget && targets.includes(activeTarget) ? activeTarget : targets[0];

  // Shared by the untargeted rows and the per-target ones. A directional gesture is ONE row
  // until it is split, whether its halves are separate bindings (the dial) or the two ends of
  // an axis pair -- same row, same checkbox either way.
  function renderGestureRow(b) {
    const pair = pairFor(b.behavior);
    const axis = axisFor(b.behavior);
    if (isPairHalf(b.behavior) && !pairForHalf(b.behavior)?.split) return null;
    const isSplit = axis ? openAxes.has(b.behavior) : !!pair?.split;
    return (
      <Fragment key={b.id}>
        <GestureRow actions={actions} onPick={pickBinding}
          dev={deviceByGesture[b.behavior]}
          b={{ ...b, pairedSplit: isSplit }}
          selected={selectedBindingId === b.id}
          onSelect={isSplit ? undefined : setSelectedBindingId}
          extra={(pair || axis) && (
            // The row itself selects for the palette, so the toggle has to stop the click
            // reaching it -- otherwise ticking split just selects the row.
            <label className="split-toggle" title="Bind each direction separately."
              onClick={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={isSplit} disabled={!!busy}
                onChange={(e) => axis
                  ? toggleAxisSplit(axis, e.target.checked)
                  : toggleSplit(pair, b, e.target.checked)} />
              split
            </label>
          )} />
        {axis && isSplit && axisHalfRows(axis)}
      </Fragment>
    );
  }
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

  async function pickBinding(bindingId, opt) {
    if (!opt) return;
    try {
      await api.setModuleBinding({ bindingId, actionCode: opt.code, actionType: opt.actionType });
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Modules</h1>
          <p className="page-sub">Configure Touch, Track, and Tune modules.</p>
        </div>
        {/* Reading is a whole-device action: one read tells us which of these profiles the
            keyboard is actually carrying. Per-profile reads invited mismatch confusion. */}
        <div className="board-actions-stack">
          {/* Above the button, in space that is reserved whether or not there is a note:
              beside it, the note moved the button the moment a read finished. */}
          <div className="board-notes">
            {imported ? (
              <span className={"saved-note" + (imported.skipped ? "" : " ok")}>
                {imported.verb || "Imported"} {imported.name} — {imported.type.toLowerCase()},{" "}
                {imported.bindings} binding(s)
                {imported.skipped > 0 && ` · ${imported.skipped} entry(s) skipped`}
              </span>
            ) : readNote ? (
              <span className={"saved-note" + (readNote.captured ? "" : " ok")}>
                Read {readNote.at.toLocaleTimeString()} — {readNote.slots} module(s) on the keyboard
                {readNote.captured > 0 &&
                  ` · captured ${readNote.captured} profile(s) the board was running`}
              </span>
            ) : device ? (
              /* Hydrated from the backend's record of the last read. It says AS OF,
                  because that is all it can honestly claim -- the board may have been
                  unplugged or flashed by NayaFlow since. */
              <span className="saved-note">
                {Object.keys(device).length} module(s) on the keyboard
                {deviceStateIsStored() && deviceStateAt()
                  ? ` · as of ${deviceStateAt().toLocaleTimeString()}`
                  : ""}
              </span>
            ) : null}
          </div>
          <div className="board-actions">
            <button
              className={"board-btn primary" + (justRead ? " btn-done" : "")}
              onClick={readDevice}
              disabled={reading}
              title="Read the keyboard and mark which profiles are on it"
            >
              {reading ? "Reading…" : justRead ? "✓ Read" : "⌨  Read from keyboard"}
            </button>
          </div>
        </div>
      </div>
      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      <div className="module-layout">
        <div className="module-list">
          <div className="module-add">
            <button className="board-btn" onClick={() => setAdding((v) => !v)}
                    title="Add another profile for a module. A layer can use a different profile
                           than the base layer, so more than one per module is useful.">
              + Add profile
            </button>
            {adding && (
              <div className="module-add-menu">
                {variants.map((v) => (
                  <button key={v.id} className="module-add-item" onClick={() => addProfile(v.id)}>
                    {v.label}
                    <span className="module-add-count">{v.bindings} binds</span>
                  </button>
                ))}
                {variants.length === 0 && <div className="palette-disabled">No stock profiles found.</div>}
              </div>
            )}
            <button className="board-btn" onClick={importProfile} disabled={importing}
                    title="Import a module profile from a JSON file. The file names its own
                           module type, so it lands under the right module.">
              {importing ? "Importing…" : "⭱  Import…"}
            </button>
          </div>
          {TYPE_ORDER.map((type) =>
            grouped[type] ? (
              <div key={type} className="module-group">
                <div className="module-group-title">{type}</div>
                {grouped[type].map((m) => (
                  renaming === m.id ? (
                    <input
                      key={m.id}
                      className="module-rename"
                      autoFocus
                      value={renameVal}
                      onChange={(e) => setRenameVal(e.target.value)}
                      onBlur={commitRename}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitRename();
                        if (e.key === "Escape") setRenaming(null);
                      }}
                    />
                  ) : (
                  <div key={m.id} className={"module-item-row" + (m.id === selectedId ? " active" : "")}>
                    <button
                      className={"module-item" + (m.id === selectedId ? " active" : "")
                        + (device && isLive(m.id) ? " on-device" : "")}
                      onClick={() => { setSelectedId(m.id); setActiveTarget(null); }}
                      onDoubleClick={() => startRename(m)}
                      title={
                        !device
                          ? "Double-click to rename"
                          : isLive(m.id)
                          ? `Running on the keyboard as slot ${entryFor(m.id)?.slot}`
                          : entryFor(m.id)
                          ? "Edited since the last read — the keyboard is running something else"
                          : "Not on the keyboard — flash to put it there"
                      }
                    >
                      ◉ {m.name}
                      {device && (
                        <span className={"module-dev-dot" + (isLive(m.id) ? " on" : "")}>
                          {isLive(m.id) ? "●" : "○"}
                        </span>
                      )}
                    </button>
                    <button className="module-item-x" title="Export this profile to a JSON file"
                            onClick={() => exportProfile(m)}>⭳</button>
                    <button className="module-item-x" title="Rename" onClick={() => startRename(m)}>✎</button>
                    <button className="module-item-x" title="Delete this profile"
                            onClick={() => removeProfile(m)}>✕</button>
                  </div>
                  )
                ))}
              </div>
            ) : null
          )}
        </div>

        <div className="module-detail">
          {!config ? (
            <div className="empty">No module configurations found.</div>
          ) : (
            <>
              <h2 style={{ margin: "0 0 12px" }}>◉ {config.name}</h2>
              <div className="module-tabs">
                <button className={"tab" + (tab === "bindings" ? " active" : "")} onClick={() => setTab("bindings")}>bindings</button>
                <button className={"tab" + (tab === "settings" ? " active" : "")} onClick={() => setTab("settings")}>settings</button>
              </div>
              {onDevice && (
                <div className="phase-note" style={{ marginBottom: 10 }}>
                  {isLive(config.id)
                    ? `Running on the keyboard as slot ${onDevice.slot}: ${onDevice.fieldCount} fields, everything matches.`
                    : `Edited since the last read — the keyboard is running something else in slot ${onDevice.slot}` +
                      ` (${onDevice.differs} gesture(s) differ).` +
                      (onDevice.matchedName ? ` The board's version is “${onDevice.matchedName}”.` : "")}
                  {onDevice.trailing > 0 &&
                    ` ${onDevice.trailing} trailing field(s) belong to a previous module config — harmless, left alone.`}
                </div>
              )}
              {device && !onDevice && (
                <div className="phase-note" style={{ marginBottom: 10 }}>
                  This config is not currently on the keyboard — nothing is flashed for it.
                </div>
              )}

              {tab === "bindings" && (
                <div style={{ maxWidth: 620 }}>
                  <ModuleVisual type={config.type} activeButton={curTarget} />

                  {untargeted.length > 0 && (
                    <>
                      <div className="skp-head"><span>Gesture</span><span className="skp-arrow">→</span><span>Action</span></div>
                      {untargeted.map(renderGestureRow)}
                    </>
                  )}

                  {targets.length > 0 && (
                    <>
                      <div className="module-btn-tabs">
                        {targets.map((t) => (
                          <button key={t} className={"tab" + (curTarget === t ? " active" : "")} onClick={() => setActiveTarget(t)}>
                            {targetLabel(t)}
                          </button>
                        ))}
                      </div>
                      {targetBindings.map(renderGestureRow)}
                    </>
                  )}
                </div>
              )}

              {tab === "settings" && (
                <div style={{ marginTop: 16, maxWidth: 640 }}>
                  {config.settingsSchema.map((f) => (
                    <div className="setting" key={f.id}>
                      <div className="setting-head">
                        <strong>{f.label}</strong>
                        {f.kind === "toggle" ? (
                          <button
                            className={"toggle" + (f.value ? " on" : "")}
                            onClick={() => setSetting(f.id, !f.value)}
                            aria-label={f.label}
                          >
                            <span className="toggle-knob" />
                          </button>
                        ) : (
                          <span className="setting-val">{f.value}</span>
                        )}
                      </div>
                      <div className="setting-desc">
                        {f.desc}
                        {f.writable === false && (
                          <span className="setting-apponly" title="We have not established which device field holds this, so writing it would be a guess. It is stored in the app and left alone on the keyboard.">
                            {" "}· app only
                          </span>
                        )}
                      </div>
                      {f.kind === "slider" && (
                        <input
                          type="range"
                          min={f.min}
                          max={f.max}
                          value={f.value}
                          onChange={(e) => setSetting(f.id, Number(e.target.value))}
                          style={{ width: "100%" }}
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* Inside the layout grid, in the SAME column as the module content, so the profile
            rail beside it can run the full height of the page instead of stopping where the
            gesture list ends. Rendered unconditionally and never keyed: a conditional render
            or a key would remount the palette on every pick and reset its tab back to the
            virtual keyboard. */}
        <div className="editor-bottom modules-bottom">
          <ActionPalette
            catalog={catalog}
            context="module"
            disabled={!selectedBinding}
            disabledHint="Select a gesture above to bind it."
            filter={paletteFilter}
            onPick={pickFromPalette}
          />
        </div>
      </div>
    </div>
  );
}
