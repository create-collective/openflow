import { useState } from "react";
import { api } from "../lib/api.js";

// "Flash to keyboard" — previews the diff (dry-run) first, then requires an explicit
// confirm. Confirm performs the real write: the backend takes a fresh device read first
// (needed to preserve the module->dock bindings the app does not model), checks every
// frame's ack, and verifies by reading the device back. The pre-flash read comes back in
// the result as a backup.

function summarize(ops) {
  const g = { layers: 0, colors: 0, modules: 0, timeouts: 0 };
  for (const op of ops || []) {
    if (op.label?.startsWith("layer")) g.layers++;
    else if (op.label?.startsWith("led")) g.colors++;
    else if (op.label?.startsWith("module")) g.modules++;
    else if (op.label?.startsWith("timeout")) g.timeouts++;
  }
  return g;
}

export default function FlashButton() {
  const [state, setState] = useState("idle"); // idle | loading | preview | writing | done | error
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  async function openPreview() {
    setState("loading");
    setError("");
    try {
      const res = await api.flashPreview();
      setPreview(res);
      setState("preview");
    } catch (e) {
      setError(e.message || String(e));
      setState("error");
    }
  }

  async function confirmFlash() {
    setState("writing");
    setError("");
    try {
      const res = await api.flash({ full: false });
      setResult(res);
      // "verified" = every ack was good AND the read-back matched. Anything else is a
      // problem the user needs to see, not a success with a caveat.
      setState(res.status === "verified" ? "done" : "error");
      if (res.status !== "verified") {
        setError(res.reason || `flash finished as "${res.status}" — check the device`);
      }
    } catch (e) {
      setError(e.message || String(e));
      setState("error");
    }
  }

  function close() {
    setState("idle");
    setPreview(null);
    setResult(null);
    setError("");
  }

  const s = preview?.summary;
  const g = s ? summarize(s.ops) : null;

  return (
    <>
      <button className="flash-btn" onClick={openPreview} disabled={state === "loading"}>
        {state === "loading" ? "Previewing…" : "⚡ Flash to keyboard"}
      </button>

      {(state === "preview" || state === "error") && (
        <div className="modal-backdrop" onClick={close}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Flash to keyboard</h3>

            {state === "error" && <p className="modal-error">Preview failed: {error}</p>}

            {state === "preview" && s && (
              <>
                <p className="modal-sub">
                  Preview (dry run) — nothing is written until you confirm.
                </p>
                <ul className="flash-diff">
                  <li><b>{g.layers}</b> layer{g.layers === 1 ? "" : "s"}</li>
                  <li><b>{g.colors}</b> colour map{g.colors === 1 ? "" : "s"}</li>
                  {g.modules > 0 && <li><b>{g.modules}</b> module config{g.modules === 1 ? "" : "s"}</li>}
                  {g.timeouts > 0 && <li>timeouts</li>}
                  <li className="flash-diff-tot">
                    {s.total_frames} frames · {s.total_bytes} bytes → {s.dest}
                  </li>
                </ul>
                <details className="flash-ops">
                  <summary>Write plan ({s.ops.length} ops)</summary>
                  <table>
                    <tbody>
                      {s.ops.map((op, i) => (
                        <tr key={i}>
                          <td>{op.label}</td>
                          <td className="mono">{op.sub}</td>
                          <td>{op.payload_bytes} B</td>
                          <td>{op.frames} fr</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            )}

            {state === "writing" && (
              <div className="phase-note">Writing to the keyboard — do not unplug it.</div>
            )}
            {state === "done" && result && (
              <div className="phase-note">
                Flashed and verified: {result.ops} operation(s), {result.frames} frame(s),
                read back with no differences.
              </div>
            )}

            <div className="modal-actions">
              <button className="btn-secondary" onClick={close}>
                {state === "done" ? "Close" : "Cancel"}
              </button>
              {state !== "done" && (
                <button
                  className="btn-primary"
                  onClick={confirmFlash}
                  disabled={state === "writing"}
                  title="Writes this profile to the keyboard, then reads it back to verify"
                >
                  {state === "writing" ? "Writing…" : "Confirm flash"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
