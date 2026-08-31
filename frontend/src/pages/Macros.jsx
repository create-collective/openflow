import { useEffect, useState } from "react";
import { api } from "../lib/api";

// Macro editor. Naya never shipped one; ZMK supports macros and the schema is
// ready, so we build a working editor: create macros, add ordered steps
// (Key / Text / Wait), persisted offline to SQLite.

function StepRow({ step, index, count, onDelete, onMove }) {
  let label;
  if (step.kind === "key") label = `Key: ${step.actionCode || "?"} (${step.state})`;
  else if (step.kind === "text") label = `Text: "${step.input}"`;
  else if (step.kind === "wait") label = "Wait for release";
  else label = step.kind;
  return (
    <div className="skp-row" style={{ cursor: "default" }}>
      <span className="skp-beh">{step.orderId + 1}</span>
      <span className="skp-arrow">→</span>
      <span className="skp-act">{label}</span>
      <span style={{ color: "var(--text-dim)", marginRight: 8 }}>{step.delay}ms</span>
      <button className="skp-x" disabled={index === 0} onClick={() => onMove(index, -1)} title="Move up">↑</button>
      <button className="skp-x" disabled={index === count - 1} onClick={() => onMove(index, 1)} title="Move down">↓</button>
      <button className="skp-x" onClick={() => onDelete(step.id)} title="Delete step">✕</button>
    </div>
  );
}

export default function Macros() {
  const [macros, setMacros] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [err, setErr] = useState(null);
  const [newName, setNewName] = useState("");
  const [stepKind, setStepKind] = useState("key");
  const [keyCode, setKeyCode] = useState("A");
  const [keyState, setKeyState] = useState("tap");
  const [textVal, setTextVal] = useState("");
  const [delay, setDelay] = useState(30);

  async function load() {
    try {
      const r = await api.macros();
      setMacros(r.macros || []);
    } catch (e) {
      setErr(e.message);
    }
  }
  useEffect(() => {
    load();
  }, []);

  const macro = macros.find((m) => m.id === selectedId) || null;

  async function createMacro() {
    if (!newName.trim()) return;
    const r = await api.createMacro(newName.trim());
    setNewName("");
    await load();
    setSelectedId(r.id);
  }

  async function addStep() {
    if (!macro) return;
    const body = { macroId: macro.id, kind: stepKind, delay: Number(delay) || 30 };
    if (stepKind === "key") { body.actionCode = keyCode; body.state = keyState; }
    if (stepKind === "text") body.input = textVal;
    await api.addMacroStep(body);
    setTextVal("");
    await load();
  }

  return (
    <div>
      <h1 className="page-title">Macros</h1>
      <p className="page-sub">Record ordered sequences of key, text, and wait steps.</p>
      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      <div className="module-layout">
        <div className="module-list">
          <div className="module-group-title">Macros</div>
          {macros.length === 0 && <div className="empty" style={{ padding: 16 }}>No macros yet.</div>}
          {macros.map((m) => (
            <button
              key={m.id}
              className={"module-item" + (m.id === selectedId ? " active" : "")}
              onClick={() => setSelectedId(m.id)}
            >
              ⚡ {m.name} <span style={{ color: "var(--text-dim)" }}>({m.steps.length})</span>
            </button>
          ))}
          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            <input
              className="mac-input"
              placeholder="New macro name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createMacro()}
            />
            <button className="btn primary" onClick={createMacro}>Add</button>
          </div>
        </div>

        <div className="module-detail">
          {!macro ? (
            <div className="empty">Select or create a macro to edit its steps.</div>
          ) : (
            <>
              <h2 style={{ margin: "0 0 4px" }}>⚡ {macro.name}</h2>
              <div className="btn-row" style={{ margin: "0 0 16px" }}>
                <button className="btn danger" onClick={async () => {
                  await api.deleteMacro(macro.id);
                  setSelectedId(null);
                  await load();
                }}>Delete macro</button>
              </div>

              <div className="skp-head"><span>Step</span><span className="skp-arrow">→</span><span>Action</span></div>
              {macro.steps.length === 0 && <div className="empty">No steps yet. Add one below.</div>}
              {macro.steps.map((s, i) => (
                <StepRow
                  key={s.id}
                  step={s}
                  index={i}
                  count={macro.steps.length}
                  onDelete={async (id) => { await api.deleteMacroStep(id); await load(); }}
                  onMove={async (index, dir) => {
                    const ids = macro.steps.map((x) => x.id);
                    const j = index + dir;
                    if (j < 0 || j >= ids.length) return;
                    [ids[index], ids[j]] = [ids[j], ids[index]];
                    await api.reorderMacroSteps(macro.id, ids);
                    await load();
                  }}
                />
              ))}

              <div className="card" style={{ marginTop: 20, maxWidth: 620 }}>
                <h3>Add step</h3>
                <div className="btn-row" style={{ marginBottom: 12 }}>
                  {["key", "text", "wait"].map((k) => (
                    <button key={k} className={"btn" + (stepKind === k ? " primary" : "")} onClick={() => setStepKind(k)}>
                      {k === "key" ? "Key" : k === "text" ? "Text" : "Wait"}
                    </button>
                  ))}
                </div>
                {stepKind === "key" && (
                  <div className="btn-row" style={{ marginBottom: 12 }}>
                    <input className="mac-input" value={keyCode} onChange={(e) => setKeyCode(e.target.value.toUpperCase())} placeholder="Action code (e.g. A)" />
                    <select className="mac-input" value={keyState} onChange={(e) => setKeyState(e.target.value)}>
                      <option value="tap">tap</option>
                      <option value="press">press</option>
                      <option value="release">release</option>
                    </select>
                  </div>
                )}
                {stepKind === "text" && (
                  <div style={{ marginBottom: 12 }}>
                    <input className="mac-input" style={{ width: "100%" }} value={textVal} onChange={(e) => setTextVal(e.target.value)} placeholder="Text to type" />
                  </div>
                )}
                <div className="btn-row">
                  <label style={{ color: "var(--text-muted)" }}>
                    Delay (ms):{" "}
                    <input className="mac-input" style={{ width: 80 }} type="number" value={delay} onChange={(e) => setDelay(e.target.value)} />
                  </label>
                  <button className="btn primary" onClick={addStep}>Add step</button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
