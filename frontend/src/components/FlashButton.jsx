import { useState } from "react";
import { invalidateDeviceState } from "../lib/deviceState";
import useDoneFlag from "../lib/useDoneFlag";
import { api } from "../lib/api.js";

// "Flash to keyboard" — previews the diff (dry-run) first, then requires an explicit
// confirm. Confirm performs the real write: the backend takes a fresh device read first
// (needed to preserve the module->dock bindings the app does not model), checks every
// frame's ack, and verifies by reading the device back. The pre-flash read comes back in
// the result as a backup.

// The profile the Bindings page has selected. A flash MUST name one: the layers table spans
// every profile, so an unscoped plan would write whichever one the DB happened to return last.
// If nothing is selected we send nothing and let the backend refuse by name -- better than
// guessing which keymap goes on the keyboard.
function activeProfileId() {
  try {
    return localStorage.getItem("openflow.activeProfile") || undefined;
  } catch {
    return undefined;
  }
}

// Has the keyboard been read in this app session? The normal flow is connect -> read ->
// edit -> flash, so that the plan is built against the board's real state. Without a read the
// app is guessing at what it is overwriting.
function hasReadDevice() {
  try {
    return Boolean(sessionStorage.getItem("openflow.deviceRead"));
  } catch {
    return false;
  }
}

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

export default function FlashButton({ variant = "sidebar" }) {
  const [state, setState] = useState("idle"); // idle | loading | preview | writing | done | error
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [wrote, setWrote] = useState(false);   // did this attempt reach the device?
  const readOk = hasReadDevice();

  // The dialog reports the result, but it gets closed. A flash is slow, irreversible and easy
  // to be unsure about, so the button carries the answer for a few seconds afterwards too.
  const [flashed, markFlashed] = useDoneFlag();

  async function openPreview() {
    setState("loading");
    setError("");
    setWrote(false);
    try {
      const res = await api.flashPreview({ profileId: activeProfileId() });
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
    setWrote(true);
    try {
      // Whatever we believed was on the device is now stale, whether this succeeds or not.
      invalidateDeviceState("flash");
      const res = await api.flash(
        recovery
          ? { mode: "recovery", acknowledgeRecovery: true, profileId: activeProfileId() }
          : { full: false, profileId: activeProfileId() });
      setResult(res);
      // "verified" = every ack was good AND the read-back matched. Anything else is a
      // problem the user needs to see, not a success with a caveat.
      setState(res.status === "verified" ? "done" : "error");
      if (res.status === "verified") markFlashed();
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
    setWrote(false);
  }

  const s = preview?.summary;
  const g = s ? summarize(s.ops) : null;

  return (
    <>
      <button
        className={
          (variant === "toolbar" ? "board-btn primary" : "flash-btn") +
          (flashed ? " btn-done" : "")
        }
        onClick={openPreview}
        disabled={state === "loading" || state === "writing"}
        title={
          flashed
            ? "Flashed and verified"
            : "Preview the changes, then confirm to write them to the keyboard"
        }
      >
        {state === "loading"
          ? "Previewing…"
          : state === "writing"
          ? "Flashing…"
          : flashed
          ? "✓ Flashed"
          : "⚡ Flash to keyboard"}
      </button>

      {/* Kept open through "writing" and "done". It used to render for preview|error only, so
          confirming unmounted the whole dialog mid-write: the "do not unplug it" note and the
          verified summary below were unreachable, and a flash finished with no signal at all.
          The backdrop stops dismissing while a write is in flight -- there is nothing to go
          back to, and the click would only hide the one thing worth watching. */}
      {state !== "idle" && state !== "loading" && (
        <div className="modal-backdrop" onClick={state === "writing" ? undefined : close}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>
              {state === "writing" ? "Flashing…" : state === "done" ? "Flashed ✓" : "Flash to keyboard"}
            </h3>

            {state === "error" && (
              <p className="modal-error">
                {wrote ? "Flash failed" : "Preview failed"}: {error}
              </p>
            )}

            {(state === "preview" || state === "writing") && s && (
              <>
                {state === "preview" && (
                  <p className="modal-sub">
                    Preview (dry run) — nothing is written until you confirm.
                  </p>
                )}
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

            {!readOk && !recovery && (
              <div className="phase-note">
                Read the keyboard first (Bindings → Read from keyboard). Flashing without it
                would write over a state the app has not seen.
              </div>
            )}
            {recovery && (
              <div className="phase-note">
                <strong>Recovery flash.</strong> The board is not read first, so nothing can be
                preserved: module-to-dock assignments, transparent keys and double-tap bindings
                are all overwritten. Only use this if the keyboard cannot be read.
              </div>
            )}
            {state === "writing" && (
              <div className="phase-note">
                <span className="flash-spinner" aria-hidden="true" />
                Writing to the keyboard, then reading it back to verify — do not unplug it.
              </div>
            )}
            {state === "done" && result && (
              <div className="phase-note flash-ok">
                <strong>Flashed and verified.</strong> {result.ops} operation(s),{" "}
                {result.frames} frame(s), read back with no differences.
              </div>
            )}

            <div className="modal-actions">
              <button className="btn-secondary" onClick={close} disabled={state === "writing"}>
                {state === "done" ? "Close" : "Cancel"}
              </button>
              {state !== "done" && !readOk && !recovery && (
                <button
                  className="btn-secondary"
                  onClick={() => setRecovery(true)}
                  title="For a keyboard that can no longer be read. Overwrites everything."
                >
                  Can't read the board?
                </button>
              )}
              {state !== "done" && (
                <button
                  className="btn-primary"
                  onClick={confirmFlash}
                  disabled={state === "writing" || (!readOk && !recovery)}
                  title={
                    recovery
                      ? "Overwrites the keyboard without reading it first"
                      : readOk
                      ? "Writes this profile to the keyboard, then reads it back to verify"
                      : "Read the keyboard first"
                  }
                >
                  {state === "writing"
                    ? "Writing…"
                    : recovery
                    ? "Recovery flash (overwrites everything)"
                    : "Confirm flash"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
