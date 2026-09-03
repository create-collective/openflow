import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";

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

function GestureRow({ b, actions, onPick, dev }) {
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
  const badge = b.flashable
    ? { cls: "flashable", text: "flashable", title: "This gesture is stored on the device and can be flashed." }
    : b.fieldKind === "axis"
    ? { cls: "axis", text: "axis", title: "Scroll/pointer routing — writing this is not confirmed yet." }
    : { cls: "dbonly", text: "app only", title: "No device field for this gesture yet — edits stay in the app until confirmed." };
  return (
    <div className="skp-row" style={{ cursor: "default" }}>
      <span className="skp-beh" style={{ textTransform: "capitalize" }}>
        {(b.gesture || "").replace(/_/g, " ")}
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
      <span className="skp-arrow">→</span>
      <select
        className="mac-input mod-action"
        value={b.actionCode || ""}
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
  const [device, setDevice] = useState(null);
  const [reading, setReading] = useState(false);
  const [variants, setVariants] = useState([]);
  const [adding, setAdding] = useState(false);      // the "add profile" dropdown
  const [renaming, setRenaming] = useState(null);   // config id being renamed
  const [renameVal, setRenameVal] = useState("");
  const [searchParams] = useSearchParams();
  const wantType = (searchParams.get("type") || "").toUpperCase();

  async function load() {
    try {
      const r = await api.modules();
      const mods = r.modules || [];
      api.moduleVariants().then((v) => setVariants(v.variants || [])).catch(() => {});
      setModules(mods);
      setActions(r.actions || []);
      if (!selectedId && mods.length) {
        // Prefer a config matching ?type= (from a Bindings module click).
        const match = wantType && mods.find((m) => m.type === wantType);
        setSelectedId((match || mods[0]).id);
      }
    } catch (e) {
      setErr(e.message);
    }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

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

  async function readDevice() {
    setReading(true);
    setErr(null);
    try {
      const r = await api.readModules();
      const byUuid = {};
      for (const m of r.modules || []) byUuid[m.uuid] = m;
      setDevice(byUuid);
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
  const onDevice = device && config ? device[config.id] : null;
  const deviceByGesture = useMemo(() => {
    const g = {};
    for (const x of onDevice?.gestures || []) g[x.gesture] = x;
    return g;
  }, [onDevice]);

  const axes = useMemo(
    () => (config?.bindings || []).filter((b) => !b.target).sort(byGesture),
    [config]
  );
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
        <div className="board-actions">
          <button className="board-btn primary" onClick={readDevice} disabled={reading}
                  title="Read the keyboard and mark which profiles are on it">
            {reading ? "Reading…" : "⌨  Read from keyboard"}
          </button>
          {device && (
            <span className="saved-note">
              {Object.keys(device).length} profile(s) on the keyboard
            </span>
          )}
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
                        + (device && device[m.id] ? " on-device" : "")}
                      onClick={() => { setSelectedId(m.id); setActiveTarget(null); }}
                      onDoubleClick={() => startRename(m)}
                      title={
                        !device
                          ? "Double-click to rename"
                          : device[m.id]
                          ? `On the keyboard as slot ${device[m.id].slot}`
                          : "Not on the keyboard — flash to put it there"
                      }
                    >
                      ◉ {m.name}
                      {device && (
                        <span className={"module-dev-dot" + (device[m.id] ? " on" : "")}>
                          {device[m.id] ? "●" : "○"}
                        </span>
                      )}
                    </button>
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
                  On the keyboard as slot {onDevice.slot}: {onDevice.fieldCount} fields,{" "}
                  {onDevice.differs === 0
                    ? "everything matches the app."
                    : `${onDevice.differs} gesture(s) differ from the app.`}
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

                  {axes.length > 0 && (
                    <>
                      <div className="skp-head"><span>Gesture</span><span className="skp-arrow">→</span><span>Action</span></div>
                      {axes.map((b) => (
                        <GestureRow key={b.id} b={b} actions={actions} onPick={pickBinding} dev={deviceByGesture[b.behavior]} />
                      ))}
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
                      {targetBindings.map((b) => (
                        <GestureRow key={b.id} b={b} actions={actions} onPick={pickBinding} dev={deviceByGesture[b.behavior]} />
                      ))}
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
                      <div className="setting-desc">{f.desc}</div>
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
      </div>
    </div>
  );
}
