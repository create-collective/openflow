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
const KEYPRESS_TYPES = new Set(["key", "modifier", "shortcut_alias"]);
function okForKind(actionType, fieldKind) {
  if (actionType === "none") return true;
  if (fieldKind === "keypress") return KEYPRESS_TYPES.has(actionType);
  if (fieldKind === "axis") return actionType === "value";
  return true; // no device field (DB-only) — don't restrict, but the row is badged
}

function GestureRow({ b, actions, onPick }) {
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
  const [searchParams] = useSearchParams();
  const wantType = (searchParams.get("type") || "").toUpperCase();

  async function load() {
    try {
      const r = await api.modules();
      const mods = r.modules || [];
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

  const grouped = useMemo(() => {
    const g = {};
    for (const m of modules) (g[m.type] ||= []).push(m);
    return g;
  }, [modules]);

  const config = modules.find((m) => m.id === selectedId) || null;

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
      <h1 className="page-title">Modules</h1>
      <p className="page-sub">Configure Touch, Track, and Tune modules.</p>
      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      <div className="module-layout">
        <div className="module-list">
          {TYPE_ORDER.map((type) =>
            grouped[type] ? (
              <div key={type} className="module-group">
                <div className="module-group-title">{type}</div>
                {grouped[type].map((m) => (
                  <button
                    key={m.id}
                    className={"module-item" + (m.id === selectedId ? " active" : "")}
                    onClick={() => { setSelectedId(m.id); setActiveTarget(null); }}
                  >
                    ◉ {m.name}
                  </button>
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

              {tab === "bindings" && (
                <div style={{ maxWidth: 620 }}>
                  <ModuleVisual type={config.type} activeButton={curTarget} />

                  {axes.length > 0 && (
                    <>
                      <div className="skp-head"><span>Gesture</span><span className="skp-arrow">→</span><span>Action</span></div>
                      {axes.map((b) => (
                        <GestureRow key={b.id} b={b} actions={actions} onPick={pickBinding} />
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
                        <GestureRow key={b.id} b={b} actions={actions} onPick={pickBinding} />
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
