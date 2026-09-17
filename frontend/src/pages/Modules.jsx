import { confirmDialog } from "../lib/dialogs";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useSyncExternalStore } from "react";
import { subscribeDeviceState, getDeviceState, setModuleRead, deviceStateAt,
         deviceStateIsStored } from "../lib/deviceState";
import { useSearchParams } from "react-router-dom";
import ActionPalette from "../components/ActionPalette";
import { shortcutLabel, shortcutTooltip, shortcutInfo,
         setShortcutTableFromActions } from "../lib/shortcutNames";
import { api } from "../lib/api";
import SettingField from "../components/SettingField";
import { downloadJSON, pickJSONFile, safeName } from "../lib/files";
import useDoneFlag from "../lib/useDoneFlag";
import { MOUSE_DIRECTIONS } from "../lib/mousedict";

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
// The name the catalog gives an action, falling back to the tidied code. Without this the
// palette button reads "Vertical Scroll" and the row it writes reads
// "mouse / SCROLL UP / SCROLL DOWN" -- the same value under two different names, and the
// uglier one is the one that sticks around after the click.
function makeLabelFor(actions) {
  const byCode = new Map((actions || []).filter((a) => a.code).map((a) => [a.code, a.label]));
  // The eight single directions a split half can hold are not catalog actions -- they are the
  // halves of the motion pairs -- so their names come from the mouse dictionary.
  for (const d of MOUSE_DIRECTIONS) if (!byCode.has(d.code)) byCode.set(d.code, d.label);
  return (code) => (code && byCode.get(code)) || cleanCode(code);
}

// A RAW_ code is the decoder saying it could not name what the field holds. Two different
// things arrive here and they must not be flattened into one:
//
//   RAW_p00:00m00  a KEY_PRESS whose payload is all zeros -- page 0, usage 0, no modifiers. It
//                  presses nothing, but it is NOT unbound: an unbound field has record type
//                  NONE and no payload at all. The board carries this on the Tune gestures
//                  NayaFlow labels LED Brightness, i.e. a gesture the keyboard handles itself
//                  and never reports to the host.
//   RAW_<hex>      bytes we genuinely cannot name yet.
//
// Neither is "Unassigned", and saying so would be inventing knowledge -- the whole point of the
// RAW prefix is that we do not have it. Both render muted, like a placeholder rather than a
// value, which is the look that was actually being asked for.
function displayAction(code, labelFor) {
  if (!code) return { text: "Unassigned", muted: true };
  if (code === "RAW_p00:00m00") {
    return { text: "Keyboard action", muted: true,
             title: "The keyboard claims this gesture and handles it itself — it sends nothing to "
                  + "the computer. This is what the board stores for its own LED brightness "
                  + "gestures. It is not the same as unassigned." };
  }
  if (code.startsWith("RAW_")) {
    return { text: "Unrecognised", muted: true,
             title: `The field holds ${code.slice(4)}, which OpenFlow cannot name yet. It is left `
                  + "exactly as it is unless you bind something else here." };
  }
  return { text: labelFor(code), muted: false };
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

// What the keyboard has for one gesture, or one half of one. Shared, because the axis halves
// were hand-built rows that simply never rendered it -- so a split Tune axis showed no ON DEVICE
// mark while the dial (whose halves are separate behaviors, and so go through GestureRow) did.
function DeviceBadge({ dev }) {
  if (!dev) return null;
  return (
    <span
      className={"gesture-badge " + (dev.differs ? "dbonly" : "flashable")}
      title={dev.differs
        ? `On the keyboard this is ${dev.device ?? "unbound"}; the app has ${dev.app || "nothing"}. Flash to make them match.`
        : `Matches what is on the keyboard (field ${"0x" + (dev.field ?? 0).toString(16)}).`}
    >
      {dev.differs ? `device: ${dev.device ?? "unbound"}` : "on device"}
    </span>
  );
}

// One badge, used by the gesture rows AND the axis half rows. They were built separately, so
// the halves carried no status badge at all -- a field that IS flashable looked identical to
// one that is app-only. Their hand-built divergence is called out twice in the comments below
// as the cause of past bugs, so the shared bits move here rather than being copied again.
function statusBadge({ unsupported, flashable, locked }) {
  if (locked) {
    return { cls: "flashable", text: "firmware",
             title: "The module's firmware does this itself while the field is empty, and the keyboard is flashed that way. NayaFlow locks it too." };
  }
  if (unsupported) {
    return { cls: "dbonly", text: "experimental",
             title: "The Track has one field per button and no room for a hold. NayaFlow lets you set one and silently overwrites the tap; we do not." };
  }
  if (flashable) {
    return { cls: "flashable", text: "flashable",
             title: "This gesture is stored on the device and can be flashed." };
  }
  return { cls: "dbonly", text: "app only",
           title: "No device field for this gesture yet — edits stay in the app until confirmed." };
}

function GestureRow({ b, dev, extra, selected, onSelect, labelFor = cleanCode }) {
  // A Track hold has no device field at all: the capture showed NayaFlow writing the hold value
  // over the tap and the tap never reaching the board. Offering it as editable would be
  // offering to lose the tap, so it renders disabled.
  // A Track hold has no device field at all. A split parent is different: it is supported,
  // its value simply lives on the two half rows -- so it is disabled but must not wear the
  // "experimental" badge, which is specifically about a binding the hardware cannot store.
  const unsupported = /^hold:track:button_/.test(b.behavior || "");
  const splitParent = !!b.pairedSplit;
  // Firmware-driven (the Touch's taps and one-finger cursor): shown, never selectable. The
  // value displayed is what the firmware does, from the server, not a row the user set.
  const locked = !!b.locked;
  const badge = statusBadge({ unsupported, flashable: b.flashable, locked });
  return (
    <div
      className={"skp-row" + (selected ? " selected" : "")}
      style={onSelect && !locked ? undefined : { cursor: "default" }}
      onClick={onSelect && !locked ? () => onSelect(b.id) : undefined}
    >
      <span className="skp-beh" style={{ textTransform: GESTURE_LABEL[b.gesture] ? "none" : "capitalize" }}>
        {GESTURE_LABEL[b.gesture] || (b.gesture || "").replace(/_/g, " ")}
      </span>
      <span className={"gesture-badge " + badge.cls} title={badge.title}>{badge.text}</span>
      <DeviceBadge dev={dev} />
      <span className="skp-arrow" title={shortcutTooltip(b.actionCode)}>→</span>
      {(() => {
        // A split parent and an unsupported row show PLACEHOLDER text, not a value, so they are
        // muted like an unassigned row. The dial already looked right only because it happens to
        // carry no actionCode; the 1-finger axis does carry one and so rendered as a real value.
        const shown = splitParent ? { text: "set per direction below", muted: true }
          : unsupported ? { text: "not settable", muted: true }
          : locked ? { text: `${displayAction(b.firmwareDefault || "", labelFor).text} (firmware)`, muted: true }
          : displayAction(b.actionCode, labelFor);
        return (
          <span className={"skp-act" + (shown.muted ? " unset" : "")}
            title={
              splitParent
                ? "Split is on — each direction is set separately below."
                : locked
                ? "Driven by the module firmware. The field is flashed empty and cannot be rebound here or in NayaFlow."
                : unsupported
                ? "The Track cannot store a hold — setting one would overwrite the tap."
                : shown.title
                || (shortcutInfo(b.actionCode) ? shortcutTooltip(b.actionCode)
                    : "Click the row, then pick an action below.")
            }>
            {shown.text}
          </span>
        );
      })()}
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
          {(() => { const bd = statusBadge({ flashable: true });
            return <span className={"gesture-badge " + bd.cls} title={bd.title}>{bd.text}</span>; })()}
          <DeviceBadge dev={deviceByGesture[`${axis.behavior}:${side}`]} />
          <span className="skp-arrow">→</span>
          <span className={"skp-act" + (code ? "" : " unset")}
            title={`device field 0x${axis.fields[side].toString(16).padStart(2, "0")}`}>
            {code ? displayAction(code, labelFor).text
              : (motionOf(side) ? `motion — ${motionOf(side)}` : "motion")}
          </span>
        </div>
      );
    });
  }

  // A human name for whatever the palette is aimed at, including axis halves, which are
  // addressed by behavior+direction rather than by a binding id.
  const selectedTargetName = useMemo(() => {
    if (!selectedBindingId) return "";
    const half = parseAxisHalfId(selectedBindingId);
    if (half) {
      const head = (half.behavior || "").split(":")[0];
      const [minusName, plusName] = AXIS_HALF_LABEL[head] || ["-", "+"];
      const axis = axisFor(half.behavior);
      const base = GESTURE_LABEL[axis?.gesture] || (axis?.gesture || head).replace(/_/g, " ");
      return `${base} · ${half.side === "-" ? minusName : plusName}`;
    }
    const b = (config?.bindings || []).find((x) => x.id === selectedBindingId);
    if (!b) return "";
    return GESTURE_LABEL[b.gesture] || (b.gesture || "").replace(/_/g, " ");
  }, [selectedBindingId, config, axisFor]);

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
  // WHICH TABS, not just which actions. `filter` only reaches the grid tabs -- the virtual
  // keyboard, the mouse and the app picker are custom render branches that never consult it, so
  // filtering alone still left a letter one click away from a field that cannot hold one.
  const paletteTabIds = useMemo(() => {
    if (!selectedBinding) return undefined;
    const isPair = selectedBinding.actionType === "value"
      || (selectedBinding.actionCode || "").includes(" - ");
    // Every direction pair we know lives in the module tab's Cursor/Scroll/Media categories,
    // and it is grid-rendered, so `filter` genuinely applies there.
    if (isPair) return ["module"];
    // A half takes a single key, or -- since 2026-09-11 -- a single motion direction from the
    // mouse tab, which renders the eight directions instead of the pairs for a half.
    if (selectedBinding.axisHalf) return ["keyboard", "mouse", "basic", "extended", "shortcuts", "apps"];
    return undefined;
  }, [selectedBinding]);

  const labelFor = useMemo(() => makeLabelFor(actions), [actions]);

  const paletteFilter = useCallback(
    (a) => {
      if (!selectedBinding) return true;
      // A compound direction pair is two device fields with the sign as direction. Only another
      // pair can go there, and `fieldKind` is null on these rows so okForKind would wave
      // anything through -- which is why the old dropdown offered all 101 actions for a field
      // that can hold five.
      const isPair = selectedBinding.actionType === "value"
        || (selectedBinding.actionCode || "").includes(" - ");
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
  // Keyed by gesture AND by "gesture:half". An axis reports TWO rows under one gesture name,
  // so keying on the name alone let the plus half overwrite the minus half -- the surviving
  // one then stood in for the whole axis, and neither half could be looked up at all.
  const deviceByGesture = useMemo(() => {
    const g = {};
    for (const x of deviceGestures) {
      if (x.half) g[`${x.gesture}:${x.half}`] = x;
      else g[x.gesture] = x;
    }
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
        <GestureRow
          labelFor={labelFor}
          dev={deviceByGesture[b.behavior]}
          b={{ ...b, pairedSplit: isSplit }}
          selected={selectedBindingId === b.id}
          onSelect={isSplit ? undefined : setSelectedBindingId}
          extra={(pair || axis) && (
            // The row itself selects for the palette, so a toggle has to stop the click
            // reaching it -- otherwise ticking one just selects the row.
            <>
              {/* Track only. Its axes are the ones you hold in your hand and can have
                  backwards; a Tune's scroll direction is a preference the OS already owns.
                  Invert is not a flag on the device -- it swaps which selector each half
                  carries -- so this is the app's record of a decision, and a read compares
                  the board against it rather than reading it back. */}
              {axis && config?.type === "TRACK" && !isSplit && (
                <label className="split-toggle" title="Swap which direction each end of this axis drives."
                  onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={!!axis.invert} disabled={!!busy}
                    onChange={(e) => setAxisInvert(b.behavior, e.target.checked)} />
                  invert
                </label>
              )}
              <label className="split-toggle" title="Bind each direction separately."
                onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={isSplit} disabled={!!busy}
                  onChange={(e) => axis
                    ? toggleAxisSplit(axis, e.target.checked)
                    : toggleSplit(pair, b, e.target.checked)} />
                split
              </label>
            </>
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
                      onClick={() => { setSelectedId(m.id); setActiveTarget(null); setSelectedBindingId(null); }}
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
                  {config.settingsSchema.map((f) => {
                    // What the keyboard holds for this setting, from the last read of the slot
                    // this profile is on. Settings are read but never silently adopted: a
                    // differing board value is shown with one click to take it.
                    const live = (onDevice?.settings || []).find((x) => x.id === f.id);
                    return (
                      <div key={f.id}>
                        {/* Shared control, not a second copy. `writable` is this schema's word
                            for the same thing `provenance` says on the Settings page: a field
                            we have capture evidence for is flashed, one we do not is app-only. */}
                        <SettingField
                          f={{ ...f, provenance: f.writable === false ? "app" : "verified" }}
                          onChange={setSetting} />
                        {live && live.differs && (
                          <div className="phase-note" style={{ marginTop: -6, marginBottom: 10 }}>
                            On the keyboard: <strong>{String(live.device)}</strong>
                            <button className="btn" style={{ marginLeft: 8 }}
                              onClick={() => setSetting(f.id, live.device)}
                              title="Set this profile's value to what the keyboard holds.">
                              Use the keyboard's value
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
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
          {/* What the palette is about to write to. Bindings has SelectedKeyPanel for exactly
              this; here the only cue was a .selected class on a row that can sit most of a
              screen above the palette, so it was easy to pick an action into nothing, or into
              the wrong row. */}
          <div className={"mod-target" + (selectedBinding ? " armed" : "")}>
            {selectedBinding ? (
              <>
                <span className="mod-target-label">Binding</span>
                <strong className="mod-target-name">{selectedTargetName}</strong>
                <span className="skp-arrow">→</span>
                {(() => {
                  const shown = displayAction(selectedBinding.actionCode, labelFor);
                  return <span className={"skp-act" + (shown.muted ? " unset" : "")}
                    title={shown.title}>{shown.text}</span>;
                })()}
                <button className="btn mod-target-clear" onClick={() => setSelectedBindingId(null)}>
                  Done
                </button>
              </>
            ) : (
              <span className="mod-target-label">Select a gesture above to bind it.</span>
            )}
          </div>
          <ActionPalette
            catalog={catalog}
            context="module"
            disabled={!selectedBinding}
            disabledHint="Select a gesture above to bind it."
            filter={paletteFilter}
            mouseDirections={!!selectedBinding?.axisHalf}
            tabIds={paletteTabIds}
            defaultTab={paletteTabIds && !paletteTabIds.includes("keyboard") ? paletteTabIds[0] : "keyboard"}
            onPick={pickFromPalette}
          />
        </div>
      </div>
    </div>
  );
}
