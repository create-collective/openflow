import { useState } from "react";
import { api } from "../lib/api.js";

// "Flash to keyboard" — previews the diff (dry-run) first, then requires an explicit
// confirm. Live flashing is not enabled yet (backend wet path is Phase C), so Confirm
// surfaces that clearly rather than silently doing nothing.

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
  const [state, setState] = useState("idle"); // idle | loading | preview | error | done
  const [preview, setPreview] = useState(null);
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

  function close() {
    setState("idle");
    setPreview(null);
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

            <div className="modal-actions">
              <button className="btn-secondary" onClick={close}>Cancel</button>
              <button
                className="btn-primary"
                disabled
                title="Live flashing is not enabled yet (verified encoders, dry-run only)"
              >
                Confirm flash (coming soon)
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
