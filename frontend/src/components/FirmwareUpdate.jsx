import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { dismissFlashRun, seedFlashProgress, useFlashProgress } from "../lib/deviceStream";
import { isModuleRun } from "../lib/moduleRun.js";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import Notice from "./ui/Notice";

// Updating the keyboard's own firmware: pick a version, see exactly what would be written to
// which half, then watch the run step by step (SCRUM-104).
//
// The backend does the whole thing as a supervised procedure -- back up, flash, verify against
// the backup, write an audit log (device/flash_procedure.py) -- and this is the window onto it.
// Three things about the real runs on hardware decide how this screen is built:
//
//   * it is SLOW. A single half measured four to five minutes, both halves about ten. A screen
//     that says nothing for that long is what makes someone pull the cable, and a cable pulled
//     mid-write is the one thing that actually bricks a half. So every step the procedure logs
//     is shown as it happens, including the two long silences that look like a hang and are not:
//     the bootloader erasing 648 KiB before the first chunk is acknowledged, and the half taking
//     minutes to come back to the application afterwards.
//   * the half GOES DARK. In its bootloader it does not type and shows no lights, which is
//     indistinguishable from a brick to anyone who has not been told. So it is said here, twice:
//     before starting, and while it is happening.
//   * the log is the evidence. NayaFlow once reported failure on this owner's board when the
//     flash had actually landed; only its log said what really happened. The verdict names the
//     run's id, and the log is one click away, for us and for Naya.
//
// The choice of binary is NOT made here. Left and right are different images and so are flash
// generations A and B; the backend resolves both from the half's product id before anything
// enters the bootloader (/api/firmware-update-plan), because finding out at the upload means a
// half already sitting in MCUboot.

/** One row per (step, half), in the order the procedure reached them, with the latest state. */
export function stepRows(events) {
  const rows = [];
  const index = new Map();
  for (const e of events || []) {
    if (e.step === "run.start" || e.step === "run.end") continue;
    const key = `${e.side || ""}:${e.step}`;
    let row = index.get(key);
    if (!row) {
      row = { key, step: e.step, side: e.side, label: e.label || e.step };
      index.set(key, row);
      rows.push(row);
    }
    // "note" is an advisory logged against verify.compare; it must not turn the row green, and
    // a failure must never be overwritten by a later note on the same step.
    if (e.phase === "fail") row.failed = true;
    else if (e.phase === "ok" && !row.failed) row.done = true;
    if (e.percent != null) row.percent = e.percent;
    if (e.took_ms != null) row.tookMs = e.took_ms;
    if (e.detail) row.detail = e.detail;
  }
  return rows;
}

/** What the headline says we are doing right now: the last step that started and has not ended. */
export function currentLabel(rows) {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (!rows[i].done && !rows[i].failed) return rows[i].label;
  }
  return rows.length ? rows[rows.length - 1].label : "Starting";
}

function duration(ms) {
  if (ms == null) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function sideName(side) {
  return side === "left" ? "Left half" : side === "right" ? "Right half" : "Keyboard";
}

export default function FirmwareUpdate({ connected, dockedModules = [] }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState(null);
  const [version, setVersion] = useState("");
  const [chosen, setChosen] = useState({});
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState("");
  const [logText, setLogText] = useState("");
  // Replacing firmware we hold no copy of is allowed, but only once the user has read that it
  // cannot be put back. Cleared whenever the choice it was given for changes.
  const [acceptUnknown, setAcceptUnknown] = useState(false);
  const { run: anyRun, events: anyEvents } = useFlashProgress();
  // The stream carries module runs too (device/module_procedure.py); this dialog shows keyboard
  // runs only, or a module run's steps would be drawn as a keyboard flash.
  const run = anyRun && !isModuleRun(anyRun) ? anyRun : null;
  const events = run ? anyEvents : [];

  const running = !!run?.running;
  const rows = stepRows(events);

  // The plan is re-resolved per version: which file each half takes, whether we hold it, and
  // whether it would be a downgrade are all properties of the pair (half, version).
  const load = useCallback(async (v) => {
    try {
      const p = await api.firmwareUpdatePlan(v || "");
      setPlan(p);
      return p;
    } catch (e) {
      setError(e.message || String(e));
      return null;
    }
  }, []);

  async function openDialog() {
    setError("");
    setLogText("");
    setAcceptUnknown(false);
    setOpen(true);
    const p = await load("");
    if (!p) return;
    // Default to the newest version we hold an image for. It is the list's first entry, and it
    // is only a default -- a downgrade is a legitimate repair and stays one click away.
    const first = p.versions?.[0]?.version || "";
    setVersion(first);
    const withTargets = await load(first);
    setChosen(defaultChoice(withTargets));
  }

  async function chooseVersion(v) {
    setVersion(v);
    setAcceptUnknown(false);
    const p = await load(v);
    setChosen(defaultChoice(p));
  }

  async function start() {
    setError("");
    setStarting(true);
    try {
      const targets = {};
      let older = false;
      for (const [side, t] of Object.entries(plan?.targets || {})) {
        if (!chosen[side] || !t.image || !t.present) continue;
        targets[side] = t.image;
        if (t.downgrade) older = true;
      }
      const state = await api.flashFirmware(targets, older, unknownChosen.length > 0 && acceptUnknown);
      // Show the run at once rather than waiting for the stream's first tick: the POST's reply
      // is already the run's opening snapshot.
      seedFlashProgress(state);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setStarting(false);
    }
  }

  // A window opened while a run is GOING -- a reload mid-flash -- catches up from the backend
  // rather than showing an empty list. A finished run is not brought back: reopening after one
  // offers the next flash (the log keeps the record).
  useEffect(() => {
    if (!open || run) return;
    api.flashRun(0).then((r) => {
      if (r.run?.running && !isModuleRun(r.run)) seedFlashProgress(r.run);
    }).catch(() => {});
  }, [open, run]);

  // Fetch the chosen version, then re-resolve: the same plan call decides all over again what
  // each half can take, so a successful download turns the checkboxes on by itself.
  async function fetchVersion() {
    setFetching(true);
    setFetchError("");
    try {
      const r = await api.fetchFirmware({ versions: [version] });
      const p = await load(version);
      setChosen(defaultChoice(p));
      if (r.failed) {
        const first = r.images.find((i) => !i.ok);
        setFetchError(`${r.failed} of ${r.requested} file(s) did not arrive. ${first?.reason || ""}`);
      }
    } catch (e) {
      setFetchError(e.message || String(e));
    } finally {
      setFetching(false);
    }
  }

  async function showLog() {
    if (!run?.id) return;
    try {
      const r = await api.flashLog(run.id);
      setLogText(r.text || "");
    } catch (e) {
      setError(e.message || String(e));
    }
  }

  const targets = plan?.targets || {};
  const pickable = Object.values(targets).filter((t) => t.image && t.present);
  // Missing because it has not been downloaded, as opposed to missing because the catalogue has
  // no way to get it. The first is a button; the second is a fact.
  const fetchable = Object.values(targets).some((t) => t.fetchable);
  const anyChosen = Object.entries(chosen).some(([side, on]) => on && targets[side]?.present);
  const downgrading = Object.entries(chosen)
    .some(([side, on]) => on && targets[side]?.downgrade);
  // Chosen halves running firmware OpenFlow has no copy of (a factory build, say).
  const unknownChosen = (plan?.halves || [])
    .filter((h) => chosen[h.side] && targets[h.side]?.present && targets[h.side]?.unknownCurrent);
  const needsAccept = unknownChosen.length > 0 && !acceptUnknown;
  const gateOff = plan && plan.flashEnabled === false;
  // SCRUM-114: NayaFlow's rule, "Please ensure NO modules are connected to both of your Create
  // halves". The backend refuses too; this says it before anyone presses the button.
  const docked = dockedModules.length > 0;
  const verdict = run && !run.running ? run.verdict : null;

  function close() {
    if (run && !run.running) dismissFlashRun(run.id);
    setOpen(false);
    setLogText("");
    setError("");
  }

  const footer = running ? (
    <Button disabled title="The flash is still running">Flashing…</Button>
  ) : verdict ? (
    <>
      <Button onClick={showLog}>View the log</Button>
      <Button variant="primary" onClick={close}>Close</Button>
    </>
  ) : (
    <>
      <Button onClick={close}>Cancel</Button>
      <Button
        variant={downgrading ? "danger" : "primary"}
        onClick={start}
        disabled={starting || gateOff || !anyChosen || docked || needsAccept}
        title={
          gateOff ? "Firmware flashing is switched off in this build"
            : docked ? "Undock the modules first"
            : !anyChosen ? "Choose a half to update"
            : needsAccept ? "Confirm above that the current firmware can be replaced"
            : downgrading ? "Writes an older firmware than the half runs now"
            : "Backs the keyboard up, writes the firmware, then verifies it"
        }
      >
        {starting ? "Starting…" : downgrading ? `Downgrade to ${version}` : `Flash ${version}`}
      </Button>
    </>
  );

  return (
    <>
      <Button
        onClick={openDialog}
        disabled={!connected}
        title={connected
          ? "Update the firmware the keyboard halves run"
          : "Connect the keyboard first"}
      >
        Update keyboard firmware…
      </Button>

      <Modal
        open={open}
        title={running ? "Updating keyboard firmware…"
          : verdict ? (verdict.ok ? "Keyboard firmware updated ✓" : "The firmware run did not finish")
          : "Update keyboard firmware"}
        subtitle={!running && !verdict
          ? "Nothing is written until you start, and the keyboard is backed up first."
          : undefined}
        onClose={close}
        dismissable={!running}
        width={620}
        footer={footer}
      >
        {error && <Notice tone="err" title="Firmware update">{error}</Notice>}

        {/* --- choosing ------------------------------------------------------------------- */}
        {!running && !verdict && plan && (
          <>
            {gateOff && (
              <Notice title="Flashing is switched off in this build">
                The whole procedure is wired and tested, but the gate that lets it write is set
                by the environment (OPENFLOW_ENABLE_FIRMWARE_FLASH) and is off here. Nothing
                below will be sent.
              </Notice>
            )}

            <label className="fw-version">
              <span>Firmware version</span>
              <select value={version} onChange={(e) => chooseVersion(e.target.value)}>
                {/* Most images carry a firmware version number. Everything before NayaFlow
                    1.14.5 does not -- those releases declared none -- so the catalogue names
                    them by the release span that shipped them, and saying "shipped in" after
                    one of those would repeat itself. */}
                {(plan.versions || []).map((v) => (
                  <option key={v.version} value={v.version}>
                    {v.declared
                      ? `${v.version}${v.bundle ? ` · shipped in ${v.bundle}` : ""}`
                      : `${v.version} · no version number declared`}
                  </option>
                ))}
              </select>
            </label>

            {docked && (
              <Notice tone="warn" title="Undock the modules first">
                Keyboard firmware is updated with no module docked on either half, as NayaFlow
                requires. Docked now:{" "}
                {dockedModules.map((m) => `${m.type} on the ${m.side} half`).join(", ")}.
              </Notice>
            )}

            {(plan.halves || []).length === 0 && (
              <Notice tone="warn" title="No keyboard is connected">
                Plug the keyboard in with its cable. Firmware goes over USB, one half at a time.
              </Notice>
            )}

            <ul className="fw-halves">
              {(plan.halves || []).filter((h) => h.side === "left" || h.side === "right").map((h) => {
                const t = targets[h.side] || {};
                const usable = !!t.image && !!t.present;
                return (
                  <li key={h.port} className="fw-half">
                    <input
                      type="checkbox"
                      id={`fw-${h.side}`}
                      checked={!!chosen[h.side] && usable}
                      disabled={!usable}
                      onChange={(e) => setChosen((c) => ({ ...c, [h.side]: e.target.checked }))}
                    />
                    <label htmlFor={`fw-${h.side}`} className="fw-half-name">
                      {sideName(h.side)}
                      <span className="fw-port">{h.port}</span>
                    </label>
                    <span className="fw-change">
                      {h.currentVersion || "unknown"}
                      {" → "}
                      {t.version || version}
                      {t.unchanged && " (already on it)"}
                      {t.downgrade && " (older)"}
                    </span>
                    {/* The image it would be written with -- or, when it cannot be, why not.
                        Showing the filename of an image we do not hold reads as "ready". */}
                    <span className="fw-file">{usable ? t.file : (t.reason || "no image")}</span>
                  </li>
                );
              })}
            </ul>

            {/* The images are not shipped with OpenFlow -- they are Naya's binaries -- so the
                usual reason a version cannot be flashed is simply that it has not been
                downloaded. That is a button, not an explanation. Every file is checked against
                the catalogue's own hash before it is kept (backend device/firmware_fetch.py).  */}
            {pickable.length === 0 && (plan.halves || []).length > 0 && (
              <Notice
                tone="warn"
                title={`${version} has not been downloaded yet`}
                action={fetchable && (
                  <Button onClick={fetchVersion} disabled={fetching} busy={fetching}>
                    {fetching ? "Downloading…" : `Download ${version}`}
                  </Button>
                )}
              >
                Firmware images are not shipped with OpenFlow.
                {fetchable
                  ? " Downloading gets every file this version needs — both halves, both flash"
                    + " generations — and checks each one against the catalog before keeping it."
                  : ` The catalog lists ${version}, but there is no record of where to fetch it`
                    + " from, so it cannot be downloaded here."}
              </Notice>
            )}
            {fetchError && <Notice tone="err" title="The download did not finish">{fetchError}</Notice>}

            {unknownChosen.length > 0 && (
              <Notice tone="warn" title="OpenFlow has no copy of the firmware being replaced">
                {unknownChosen.map((h) => `The ${h.side} half runs ${h.currentVersion}`).join("; ")}
                , which is not in any NayaFlow release OpenFlow knows (factory firmware, most
                likely). It is still Naya&apos;s own firmware and can be replaced safely, but once
                it is, OpenFlow cannot put it back.
                <label className="fw-accept">
                  <input type="checkbox" checked={acceptUnknown}
                    onChange={(e) => setAcceptUnknown(e.target.checked)} />
                  {" "}I understand, replace it with {version}
                </label>
              </Notice>
            )}

            {downgrading && (
              <Notice tone="warn" title="This writes an older firmware than the half runs now">
                A downgrade is a legitimate repair — it is how two halves that no longer talk to
                each other are brought back to a common version — so it is offered. It is not the
                usual thing to do, which is why it says so here.
              </Notice>
            )}

            <Notice tone="info" title="What happens, and how long it takes">
              The keyboard is read and saved first, then each half is flashed on its own and
              checked against that backup. One half took four to five minutes on the reference
              board; both halves, about ten.
              <ul className="fw-expect">
                <li>
                  The half being flashed <strong>goes dark</strong> — no lights, and it stops
                  typing — while it is in its bootloader. That is expected, and its existing
                  firmware is untouched until the new image has been written and checked.
                </li>
                <li>
                  Two steps look like a hang and are not: preparing the flash (the bootloader
                  erasing the slot) and the restart afterwards, which can take minutes.
                </li>
                <li><strong>Do not unplug the keyboard</strong> while it is running.</li>
              </ul>
            </Notice>
          </>
        )}

        {/* --- running, and the verdict ------------------------------------------------------ */}
        {(running || verdict) && (
          <>
            {running && (
              <Notice tone="warn" title="Do not unplug the keyboard">
                <span className="flash-spinner" aria-hidden="true" />
                {currentLabel(rows)}
                {run?.elapsedMs != null && (
                  <span className="fw-elapsed"> · {duration(run.elapsedMs)} so far</span>
                )}
              </Notice>
            )}

            <ol className="fw-steps">
              {rows.map((r) => (
                <li
                  key={r.key}
                  className={["fw-step",
                    r.failed ? "is-failed" : r.done ? "is-done" : "is-running"].join(" ")}
                >
                  <span className="fw-step-mark" aria-hidden="true">
                    {r.failed ? "!" : r.done ? "✓" : "…"}
                  </span>
                  <span className="fw-step-label">
                    {r.label}
                    {r.side && <span className="fw-step-side">{sideName(r.side)}</span>}
                  </span>
                  {/* Only the upload reports a percentage. The two long waits either side of it
                      deliberately have none: a bar that cannot move is worse than words that
                      say how long this takes. */}
                  {!r.done && r.percent != null && (
                    <progress className="fw-bar" value={r.percent} max="100" />
                  )}
                  <span className="fw-step-took">
                    {r.percent != null && !r.done ? `${r.percent}%` : duration(r.tookMs)}
                  </span>
                  {r.detail && <span className="fw-step-detail">{r.detail}</span>}
                </li>
              ))}
            </ol>

            {verdict && (
              <Notice
                tone={verdict.ok ? "ok" : "err"}
                title={verdict.ok
                  ? "Firmware written and verified"
                  : "The run stopped before it finished"}
              >
                {verdict.summary}
                {verdict.failures?.length > 0 && (
                  <ul className="fw-verdict-list">
                    {verdict.failures.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                )}
                {!verdict.ok && (
                  <p className="fw-verdict-note">
                    A half that is left in its bootloader is put back into the application before
                    this reports, so a keyboard that shows no lights after a failure is almost
                    certainly still fine — its existing firmware is only replaced once the new
                    image has been written and checked. The log below says exactly how far it got.
                  </p>
                )}
                {verdict.advisories?.length > 0 && (
                  <ul className="fw-verdict-list">
                    {verdict.advisories.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                )}
                <p className="fw-verdict-note">
                  Saved as <code>{run?.id}</code>. Keep it if anything looked wrong — it is what
                  we, or Naya, would need to read.
                </p>
              </Notice>
            )}

            {logText && <pre className="fw-log">{logText}</pre>}
          </>
        )}
      </Modal>
    </>
  );
}

/** Both halves that have a usable image and are not already on the chosen version. */
function defaultChoice(plan) {
  const out = {};
  for (const [side, t] of Object.entries(plan?.targets || {})) {
    out[side] = !!t.image && !!t.present && !t.unchanged;
  }
  return out;
}
