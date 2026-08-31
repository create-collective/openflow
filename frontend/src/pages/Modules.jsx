import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

// Module configuration (Touch / Track / Tune). Mirrors NayaFlow: a grouped list
// on the left, and the selected config's bindings + settings tabs in the center.
// Reads the real module_configs/module_bindings/module_settings; editing gesture
// bindings is the next iteration (settings sliders are display for now).

const TYPE_ORDER = ["TOUCH", "TRACK", "TUNE"];

function cleanCode(code) {
  if (!code) return "—";
  return code.replaceAll(" - ", " / ").replaceAll("_", " ");
}

function targetLabel(t) {
  if (!t) return "Axes & Gestures";
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function SettingSlider({ s }) {
  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <div className="kv">
        <span className="k">{s.correlationId}</span>
        <span className="v">{s.value}</span>
      </div>
      <input type="range" min="1" max="100" defaultValue={Number(s.value) || 1} disabled style={{ width: "100%" }} />
    </div>
  );
}

export default function Modules() {
  const [modules, setModules] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState("bindings");
  const [activeButton, setActiveButton] = useState("button_1");
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.modules().then((r) => {
      setModules(r.modules || []);
      if (r.modules?.[0]) setSelectedId(r.modules[0].id);
    }).catch((e) => setErr(e.message));
  }, []);

  const grouped = useMemo(() => {
    const g = {};
    for (const m of modules) (g[m.type] ||= []).push(m);
    return g;
  }, [modules]);

  const config = modules.find((m) => m.id === selectedId) || null;

  // Group bindings by their target (null target = the axis/gesture group), which
  // handles all module types: Track (axes + button_1..4), Touch (2/3/4 fingers),
  // Tune (1/2/3 fingers + dial).
  const groups = useMemo(() => {
    const g = new Map();
    for (const b of config?.bindings || []) {
      const key = b.target || "";
      if (!g.has(key)) g.set(key, []);
      g.get(key).push(b);
    }
    // null-target group first, then the rest sorted.
    return [...g.entries()].sort((a, b) => (a[0] === "" ? -1 : b[0] === "" ? 1 : a[0].localeCompare(b[0])));
  }, [config]);

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
                    onClick={() => setSelectedId(m.id)}
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
                <div>
                  {groups.length === 0 && <div className="empty">No gesture bindings.</div>}
                  {groups.map(([target, binds]) => (
                    <div key={target || "axes"} style={{ marginBottom: 20 }}>
                      <div className="module-group-title" style={{ marginLeft: 0 }}>
                        {targetLabel(target)}
                      </div>
                      <div className="skp-head">
                        <span>Gesture</span><span className="skp-arrow">→</span><span>Action</span>
                      </div>
                      {binds.map((b) => (
                        <div className="skp-row" key={b.id} style={{ cursor: "default" }}>
                          <span className="skp-beh" style={{ textTransform: "capitalize" }}>
                            {(b.gesture || "").replace(/_/g, " ")}
                          </span>
                          <span className="skp-arrow">→</span>
                          <span className="skp-act">{cleanCode(b.actionCode)}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}

              {tab === "settings" && (
                <div style={{ marginTop: 16 }}>
                  {config.settings.length === 0 ? (
                    <div className="phase-note">
                      No stored settings for this module. Speed/acceleration sliders will
                      appear here once configured (settings editing lands with device sync).
                    </div>
                  ) : (
                    config.settings.map((s) => <SettingSlider key={s.correlationId} s={s} />)
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
