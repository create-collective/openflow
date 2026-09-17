import { useEffect, useState } from "react";
import { api } from "../lib/api";
import VirtualKeyboard from "../components/VirtualKeyboard";
import { actionText } from "../lib/keylabels";
import MacroRecorder from "../components/MacroRecorder";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import IconButton from "../components/ui/IconButton";
import Notice from "../components/ui/Notice";

// Macro editor. Naya never shipped one; ZMK supports macros and the schema is
// ready, so we build a working editor: create macros, add ordered steps
// (Key / Text / Wait), persisted offline to SQLite.

function StepRow({ step, index, count, onDelete, onMove, onDelay }) {
  let label;
  if (step.kind === "key") label = `Key: ${step.actionCode || "?"} (${step.state})`;
  else if (step.kind === "text") label = `Text: "${step.input}"`;
  else if (step.kind === "wait") label = "Wait for release";
  else if (step.kind === "launch") {
    label = `Launch: ${step.program}${(step.args || []).length ? " " + step.args.join(" ") : ""}`;
  } else if (step.kind === "command") label = `Run: ${step.program}`;
  else label = step.kind;
  return (
    <div className="skp-row" style={{ cursor: "default" }}>
      <span className="skp-beh">{step.orderId + 1}</span>
      <span className="skp-arrow">→</span>
      <span className="skp-act">{label}</span>
      <span className="step-cell-delay">
        <input
          className="mac-input step-delay" type="number" min={0} max={60000}
          defaultValue={step.delay} title="Delay after this step, in milliseconds"
          onBlur={(e) => {
            const n = Number(e.target.value);
            if (Number.isFinite(n) && n !== step.delay) onDelay(step.id, n);
          }}
        />
        <span style={{ color: "var(--text-dim)" }}>ms</span>
      </span>
      <span className="step-cell-actions">
        <IconButton size="sm" disabled={index === 0} onClick={() => onMove(index, -1)} title="Move up">↑</IconButton>
        <IconButton size="sm" disabled={index === count - 1} onClick={() => onMove(index, 1)} title="Move down">↓</IconButton>
        <IconButton size="sm" tone="danger" onClick={() => onDelete(step.id)} title="Delete step">✕</IconButton>
      </span>
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
  const [program, setProgram] = useState("");
  const [argsText, setArgsText] = useState("");
  const [recording, setRecording] = useState(false);

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
    if (stepKind === "launch" || stepKind === "command") {
      if (!program.trim()) { setErr("Enter a program to run."); return; }
      body.program = program.trim();
      if (stepKind === "launch") body.args = argsText.split(/\s+/).filter(Boolean);
    }
    await api.addMacroStep(body);
    setTextVal("");
    setProgram("");
    setArgsText("");
    await load();
  }

  return (
    <div>
      <h1 className="page-title">Macros</h1>
      <p className="page-sub">Record ordered sequences of key, text, and wait steps.</p>
      <Notice style={{ maxWidth: 720, marginBottom: 16 }}>
        Macros are stored in OpenFlow but <strong>cannot be bound to a key yet</strong>. The
        keyboard reserves the macro behaviour type but implements no macro table &mdash; every
        write to it is acknowledged and discarded, and Naya&rsquo;s own software never writes one
        either. Building them here is safe; they simply do not reach the board.
      </Notice>
      {err && <Card><Notice tone="err">{err}</Notice></Card>}

      <div className="macro-layout">
        <div className="module-list macro-rail">
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
            <Button variant="primary" onClick={createMacro}>Add</Button>
          </div>
        </div>

        <div className="module-detail macro-detail">
          {!macro ? (
            <div className="empty">Select or create a macro to edit its steps.</div>
          ) : (
            <>
              <div className="macro-head">
                <h2 style={{ margin: 0 }}>
                  ⚡{" "}
                  <span
                    title="Double-click to rename"
                    onDoubleClick={() => setRenaming(macro.name)}
                    style={{ cursor: "text" }}
                  >{macro.name}</span>
                </h2>
                <span className="macro-head-count">
                  {macro.steps.length} step{macro.steps.length === 1 ? "" : "s"}
                </span>
                <Button variant="danger" onClick={async () => {
                  await api.deleteMacro(macro.id);
                  setSelectedId(null);
                  await load();
                }}>Delete macro</Button>
              </div>
              {renaming !== null && (
                <div className="btn-row" style={{ margin: "0 0 12px" }}>
                  <input className="mac-input" autoFocus value={renaming}
                    onChange={(e) => setRenaming(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveRename();
                      if (e.key === "Escape") setRenaming(null);
                    }} />
                  <Button variant="primary" onClick={saveRename}>Rename</Button>
                  <Button onClick={() => setRenaming(null)}>Cancel</Button>
                </div>
              )}

              <Card className="macro-steps">
              <div className="skp-head">
                <span style={{ minWidth: 34 }}>#</span>
                <span className="skp-arrow">→</span>
                <span style={{ flex: 1 }}>Action</span>
                <span style={{ minWidth: 96, textAlign: "right" }}>Delay</span>
                <span style={{ minWidth: 74 }} />
              </div>
              {macro.steps.length === 0 && (
                <div className="empty" style={{ padding: "18px 0" }}>
                  No steps yet. Record one below, or add them by hand.
                </div>
              )}
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

              </Card>

              <div className="macro-compose">
              <MacroRecorder
                onCommit={async (steps) => {
                  if (!steps.length) return;
                  try { await api.addMacroSteps(macro.id, steps); await load(); }
                  catch (e) { setErr(e.message); }
                }}
              />

              <Card className="macro-add" title="Add step">
                <div className="btn-row" style={{ marginBottom: 12 }}>
                  {["key", "text", "wait", "launch", "command"].map((k) => (
                    <Button key={k} variant={stepKind === k ? "primary" : "secondary"} onClick={() => setStepKind(k)}>
                      {{ key: "Key", text: "Text", wait: "Wait",
                         launch: "Launch app", command: "Run command" }[k]}
                    </Button>
                  ))}
                </div>
                {stepKind === "key" && (
                  <>
                    <div className="btn-row" style={{ marginBottom: 12, alignItems: "center" }}>
                      {/* Not .skp-act: that carries flex:1 and flung the state select to the
                          far edge of a full-width card, reading as an unrelated control. */}
                      <span className="macro-pick">
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
                {stepKind === "launch" && (
                  <div style={{ marginBottom: 12 }}>
                    <input className="mac-input" style={{ width: "100%", marginBottom: 8 }}
                      value={program} onChange={(e) => setProgram(e.target.value)}
                      placeholder="Program, e.g. C:\Windows\System32\notepad.exe or firefox" />
                    <input className="mac-input" style={{ width: "100%" }}
                      value={argsText} onChange={(e) => setArgsText(e.target.value)}
                      placeholder="Arguments, space separated (optional)" />
                    <div className="setting-desc" style={{ marginTop: 6 }}>
                      Started directly, with no shell. Arguments are passed as a list, so quoting
                      and metacharacters cannot turn into a second command.
                    </div>
                  </div>
                )}
                {stepKind === "command" && (
                  <div style={{ marginBottom: 12 }}>
                    <input className="mac-input" style={{ width: "100%" }}
                      value={program} onChange={(e) => setProgram(e.target.value)}
                      placeholder="Shell command, e.g. git status" />
                    <Notice style={{ marginTop: 8 }}>
                      This runs through a shell, so it can do anything your account can. Prefer
                      &ldquo;Launch app&rdquo; unless you genuinely need shell features like pipes
                      or redirection.
                    </Notice>
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
                  <Button variant="primary" onClick={addStep}>Add step</Button>
                </div>
              </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
