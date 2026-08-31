import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

// Module configuration (Touch / Track / Tune). Grouped list on the left; the
// selected config's bindings (module visual + always-on gestures + per-target
// tabs) and editable settings tabs in the center.

const TYPE_ORDER = ["TOUCH", "TRACK", "TUNE"];

function cleanCode(code) {
  if (!code) return "—";
  return code.replaceAll(" - ", " / ").replaceAll("_", " ");
}
function targetLabel(t) {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// The Naya module outline: rounded shape with one squared (right-angle) top-left
// corner, matching the physical module footprint.
const OUTLINE = "M2,2 L74,2 Q98,2 98,26 L98,74 Q98,98 74,98 L26,98 Q2,98 2,74 Z";
const STROKE = "var(--neutral40)";

function ModuleVisual({ type }) {
  return (
    <div className="mod-visual">
      <svg viewBox="0 0 100 100" width="150" height="150" fill="none"
        stroke={STROKE} strokeWidth="2.5">
        <path d={OUTLINE} />
        {type === "TRACK" && (
          <>
            <circle cx="50" cy="52" r="30" />
            <circle cx="50" cy="52" r="13" />
            {/* 4 segment dividers */}
            <line x1="50" y1="22" x2="50" y2="39" />
            <line x1="50" y1="65" x2="50" y2="82" />
            <line x1="20" y1="52" x2="37" y2="52" />
            <line x1="63" y1="52" x2="80" y2="52" />
            {/* trackball */}
            <circle cx="74" cy="30" r="7" fill="var(--accent)" stroke="none" opacity="0.85" />
          </>
        )}
        {type === "TUNE" && (
          <>
            <circle cx="50" cy="50" r="30" strokeWidth="9" />
            <circle cx="50" cy="50" r="15" />
          </>
        )}
        {type === "TOUCH" && <circle cx="50" cy="50" r="30" />}
      </svg>
    </div>
  );
}

export default function Modules() {
  const [modules, setModules] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState("bindings");
  const [activeTarget, setActiveTarget] = useState(null);
  const [err, setErr] = useState(null);

  async function load() {
    try {
      const r = await api.modules();
      setModules(r.modules || []);
      if (!selectedId && r.modules?.[0]) setSelectedId(r.modules[0].id);
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

  const axes = useMemo(() => (config?.bindings || []).filter((b) => !b.target), [config]);
  const targets = useMemo(() => {
    const t = [];
    for (const b of config?.bindings || []) if (b.target && !t.includes(b.target)) t.push(b.target);
    return t.sort();
  }, [config]);
  const curTarget = activeTarget && targets.includes(activeTarget) ? activeTarget : targets[0];
  const targetBindings = (config?.bindings || []).filter((b) => b.target === curTarget);

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
                  <ModuleVisual type={config.type} />

                  {axes.length > 0 && (
                    <>
                      <div className="skp-head"><span>Gesture</span><span className="skp-arrow">→</span><span>Action</span></div>
                      {axes.map((b) => (
                        <div className="skp-row" key={b.id} style={{ cursor: "default" }}>
                          <span className="skp-beh" style={{ textTransform: "capitalize" }}>{(b.gesture || "").replace(/_/g, " ")}</span>
                          <span className="skp-arrow">→</span>
                          <span className="skp-act">{cleanCode(b.actionCode)}</span>
                        </div>
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
                        <div className="skp-row" key={b.id} style={{ cursor: "default" }}>
                          <span className="skp-beh" style={{ textTransform: "capitalize" }}>{(b.gesture || "").replace(/_/g, " ")}</span>
                          <span className="skp-arrow">→</span>
                          <span className="skp-act">{cleanCode(b.actionCode)}</span>
                        </div>
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
