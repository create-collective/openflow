import { useEffect, useState } from "react";
import { api } from "../lib/api";
import VirtualKeyboard from "../components/VirtualKeyboard";
import { actionText } from "../lib/keylabels";

// Macro editor. Naya never shipped one; ZMK supports macros and the schema is
// ready, so we build a working editor: create macros, add ordered steps
// (Key / Text / Wait), persisted offline to SQLite.

function StepRow({ step, index, count, onDelete, onMove, onDelay }) {
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
      <input
        className="mac-input step-delay" type="number" min={0} max={60000}
        defaultValue={step.delay} title="Delay after this step, in milliseconds"
        onBlur={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n !== step.delay) onDelay(step.id, n);
        }}
      />
      <span style={{ color: "var(--text-dim)", marginRight: 8 }}>ms</span>
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
  const [keyCode, setKeyCode] = useState("");
  const [keyState, setKeyState] = useState("tap");
  const [keyType, setKeyType] = useState("key");
  const [textVal, setTextVal] = useState("");
  const [delay, setDelay] = useState(30);
  const [renaming, setRenaming] = useState(null);

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

  async function saveRename() {
    const name = (renaming || "").trim();
    if (!macro || !name || name === macro.name) { setRenaming(null); return; }
    try { await api.renameMacro(macro.id, name); await load(); }
    catch (e) { setErr(e.message); }
    setRenaming(null);
  }

  async function addStep() {
    if (!macro) return;
    const body = { macroId: macro.id, kind: stepKind, delay: Number(delay) || 30 };
    if (stepKind === "key") {
      if (!keyCode) { setErr("Pick a key for this step first."); return; }
      body.actionCode = keyCode; body.state = keyState;
    }
    if (stepKind === "text") body.input = textVal;
    await api.addMacroStep(body);
    setTextVal("");
    await load();
  }

  return (
    <div>
      <h1 className="page-title">Macros</h1>
      <p className="page-sub">Record ordered sequences of key, text, and wait steps.</p>
      <div className="phase-note" style={{ maxWidth: 720, marginBottom: 16 }}>
        Macros are stored in OpenFlow but <strong>cannot be bound to a key yet</strong>. The
        keyboard reserves the macro behaviour type but implements no macro table &mdash; every
        write to it is acknowledged and discarded, and Naya&rsquo;s own software never writes one
        either. Building them here is safe; they simply do not reach the board.
      </div>
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
              <h2 style={{ margin: "0 0 4px" }}>
                ⚡{" "}
                <span
                  title="Double-click to rename"
                  onDoubleClick={() => setRenaming(macro.name)}
                  style={{ cursor: "text" }}
                >{macro.name}</span>
              </h2>
              {renaming !== null && (
                <div className="btn-row" style={{ margin: "0 0 12px" }}>
                  <input className="mac-input" autoFocus value={renaming}
                    onChange={(e) => setRenaming(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveRename();
                      if (e.key === "Escape") setRenaming(null);
                    }} />
                  <button className="btn primary" onClick={saveRename}>Rename</button>
                  <button className="btn" onClick={() => setRenaming(null)}>Cancel</button>
                </div>
              )}
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
                  onDelay={async (id, ms) => { await api.updateMacroStep(id, { delay: ms }); await load(); }}
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
                  <>
                    <div className="btn-row" style={{ marginBottom: 12, alignItems: "center" }}>
                      <span className="skp-act" style={{ minWidth: 120 }}>
                        {keyCode
                          ? actionText({ actionCode: keyCode, actionType: keyType })
                          : <span style={{ color: "var(--text-dim)" }}>Pick a key below</span>}
                      </span>
                      <select className="mac-input" value={keyState}
                        onChange={(e) => setKeyState(e.target.value)}>
                        <option value="tap">tap</option>
                        <option value="press">press</option>
                        <option value="release">release</option>
                      </select>
                    </div>
                    {/* Was a bare text input: `value.toUpperCase()`, no validation, so "ASDF"
                        saved happily. This is the same picker every other binding surface uses,
                        so a step can only hold a code the rest of the app understands. */}
                    <VirtualKeyboard
                      disabled={false}
                      onPick={(pick) => { setKeyCode(pick.actionCode); setKeyType(pick.actionType); }}
                      disabledHint=""
                    />
                  </>
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
