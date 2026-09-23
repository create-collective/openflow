import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { seedFlashProgress, useFlashProgress } from "../lib/deviceStream";
import { activeBlockers, isModuleRun, replugPending, startLabel } from "../lib/moduleRun.js";
import { currentLabel, stepRows } from "./FirmwareUpdate";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import Notice from "./ui/Notice";

// Module firmware: the procedure NayaFlow runs, done by OpenFlow (backend device/
// module_procedure.py), watched from here. Kept apart from the keyboard's dialog because it is a
// different procedure with different rules (owner, 2026-09-21):
//
//   * ONLY THE LEFT HALF, ONE MODULE, IN THE LEFT BAY. NayaFlow's own words: "the only Naya Device
//     connected is a single up-to-date Create Left with the docked module". The dialog reads the
//     board first (/api/module-update-plan) and lists every precondition in plain words, so the
//     person fixes the setup before pressing anything rather than after a refusal.
//   * A BUNDLE NO NEWER THAN THE KEYBOARD. Older module firmware runs on newer keyboards; newer
//     module firmware needs the keyboard updated first. The version list says which is which.
//   * THE REPLUG. The left half restarts once or twice and sometimes does not come back on USB
//     until its cable is unplugged and plugged in again. That is asked for here, large, the moment
//     the run asks for it, and it goes away when the half is back.
//   * FORCE UPDATE, for a module that does not identify properly: the person names the module
//     (Touch or Tune -- the two whose programming byte has been captured) and a version this
//     keyboard can take. It is how a Tune given the wrong app on 2026-09-23 was brought back.

function duration(ms) {
  if (ms == null) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export default function ModuleFirmwareUpdate({ connected = true }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState(null);
  const [version, setVersion] = useState("");
  const [force, setForce] = useState(false);
  const [forceType, setForceType] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [logText, setLogText] = useState("");
  const { run, events } = useFlashProgress();

  // The stream carries keyboard runs too; this window shows module runs only.
  const mine = isModuleRun(run) ? run : null;
  const running = !!mine?.running;
  const rows = mine ? stepRows(events) : [];
  const replug = mine && running ? replugPending(events) : null;
  const verdict = mine && !mine.running ? mine.verdict : null;

  const load = useCallback(async (v) => {
    setLoading(true);
    try {
      const p = await api.moduleUpdatePlan(v || "");
      setPlan(p);
      setError("");
      return p;
    } catch (e) {
      setError(e.message || String(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  async function openDialog() {
    setLogText("");
    setOpen(true);
    const p = await load("");
    if (p?.target) setVersion(p.target.version);
    if (p?.forceTypes?.length && !forceType) setForceType(p.forceTypes[0]);
  }

  async function chooseVersion(v) {
    setVersion(v);
    await load(v);
  }

  // A window opened while a run is going catches up from the backend.
  useEffect(() => {
    if (!open || run) return;
    api.flashRun(0).then((r) => { if (r.run) seedFlashProgress(r.run); }).catch(() => {});
  }, [open, run]);

  async function start() {
    setError("");
    setStarting(true);
    try {
      const body = { version, allow_older: !!plan?.target?.downgrade };
      if (force) body.force_type = forceType;
      seedFlashProgress(await api.flashModuleFirmware(body));
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setStarting(false);
    }
  }

  async function fetchVersion() {
    if (!plan?.target?.historyPath) return;
    setFetching(true);
    try {
      await api.fetchFirmware({ paths: [plan.target.historyPath] });
      await load(version);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setFetching(false);
    }
  }

  async function showLog() {
    if (!mine?.id) return;
    try {
      setLogText((await api.flashLog(mine.id)).text || "");
    } catch (e) {
      setError(e.message || String(e));
    }
  }

  function close() {
    setOpen(false);
    setLogText("");
    setError("");
    setForce(false);
  }

  const blockers = activeBlockers(plan, force);
  const target = plan?.target;
  const { label, needed } = startLabel(plan, { force, forceType });
  const gateOff = plan && plan.flashEnabled === false;
  const needsDownload = target && !target.present;
  const canStart = !!target && !gateOff && blockers.length === 0 && !needsDownload && needed
    && (!force || !!forceType);
  const m = plan?.module;

  const footer = running ? (
    <Button disabled title="The update is still running">Updating…</Button>
  ) : verdict ? (
    <>
      <Button onClick={showLog}>View the log</Button>
      <Button variant="primary" onClick={close}>Close</Button>
    </>
  ) : (
    <>
      <Button onClick={() => load(version)} disabled={loading} title="Read the keyboard again">
        {loading ? "Checking…" : "Check again"}
      </Button>
      <Button onClick={close}>Cancel</Button>
      <Button
        variant={force || target?.downgrade ? "danger" : "primary"}
        onClick={start}
        disabled={starting || !canStart}
        title={gateOff ? "Firmware flashing is switched off in this build"
          : blockers.length ? blockers[0].text
            : needsDownload ? "Download this version first"
              : !needed ? "The module and the keyboard already hold this version"
                : "Backs the keyboard up, then updates the module"}
      >
        {starting ? "Starting…" : label}
      </Button>
    </>
  );

  return (
    <>
      <Button
        onClick={openDialog}
        disabled={!connected}
        title={connected ? "Update the firmware of the module docked in the left bay"
          : "Connect the keyboard first"}
      >
        Update module firmware…
      </Button>

      <Modal
        open={open}
        title={running ? "Updating module firmware…"
          : verdict ? (verdict.ok ? "Module firmware updated ✓" : "The module update did not finish")
            : "Update module firmware"}
        subtitle={!running && !verdict
          ? "Nothing is written until you start, and the keyboard is backed up first."
          : undefined}
        onClose={close}
        dismissable={!running}
        width={620}
        footer={footer}
      >
        {error && <Notice tone="err" title="Module update">{error}</Notice>}

        {/* --- choosing ------------------------------------------------------------------- */}
        {!running && !verdict && plan && (
          <>
            {gateOff && (
              <Notice title="Flashing is switched off in this build">
                The procedure is wired, but the gate that lets it write is set by the environment
                (OPENFLOW_ENABLE_FIRMWARE_FLASH) and is off here. Nothing will be sent.
              </Notice>
            )}

            <ul className="fw-halves">
              <li className="fw-half">
                <span className="fw-half-name">Left half</span>
                <span className="fw-change">
                  {plan.keyboardFirmware ? `keyboard ${plan.keyboardFirmware}` : "not connected"}
                </span>
                <span className="fw-file">
                  {plan.storedBundle ? `holds module firmware ${plan.storedBundle}` : ""}
                </span>
              </li>
              <li className="fw-half">
                <span className="fw-half-name">Module (left bay)</span>
                <span className="fw-change">
                  {m ? `${m.type} · ${m.firmwareVersion || "version unknown"}` : "none found"}
                </span>
              </li>
              <li className="fw-half">
                <span className="fw-half-name">Right half</span>
                <span className="fw-change">
                  {plan.rightConnected ? "connected — unplug it" : "not connected ✓"}
                </span>
              </li>
            </ul>

            {blockers.length > 0 && (
              <Notice tone="warn" title="Before this can start">
                <ul className="fw-expect">
                  {blockers.map((b) => <li key={b.code}>{b.text}</li>)}
                </ul>
              </Notice>
            )}

            <label className="fw-version">
              <span>Module firmware</span>
              <select value={version} onChange={(e) => chooseVersion(e.target.value)}>
                {(plan.versions || []).map((v) => (
                  <option key={v.version} value={v.version} disabled={!v.fits}>
                    {v.version}
                    {!v.fits ? ` · needs keyboard ${v.needsKeyboard} or newer`
                      : !v.present ? " · not downloaded" : ""}
                  </option>
                ))}
              </select>
            </label>

            {needsDownload && (
              <Notice
                tone="warn"
                title={`${target.version} has not been downloaded yet`}
                action={target.fetchable && (
                  <Button onClick={fetchVersion} disabled={fetching} busy={fetching}>
                    {fetching ? "Downloading…" : `Download ${target.version}`}
                  </Button>
                )}
              >
                Firmware is not shipped with OpenFlow. The download is checked against the
                catalogue before it is kept.
              </Notice>
            )}

            {target?.downgrade && !force && (
              <Notice tone="warn" title="This writes an older module firmware than it runs now">
                Older module firmware runs on a newer keyboard, so this is allowed. It is not the
                usual thing to do, which is why it says so.
              </Notice>
            )}

            <label className="fw-force">
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              <span>Force update: the module is not detected, or does not identify properly</span>
            </label>
            {force && (
              <Notice tone="warn" title="Force update programs the module you name, whatever it reports">
                <label className="fw-version">
                  <span>The docked module is a</span>
                  <select value={forceType} onChange={(e) => setForceType(e.target.value)}>
                    {(plan.forceTypes || []).map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </label>
                Choose the module that is physically in the left bay: programming it as the wrong
                type gives it the wrong app. A Track is not offered yet — its byte has not been
                captured.
              </Notice>
            )}

            <Notice tone="info" title="What happens, and how long it takes">
              About three to six minutes in all.
              <ul className="fw-expect">
                {target?.upload !== false && (
                  <li>
                    The left half goes into its bootloader — <strong>its lights go off</strong> —
                    for about two minutes while the module firmware is written to it.
                  </li>
                )}
                <li>
                  Then the module is programmed: its lights go out for 10–15 seconds and the
                  keyboard restarts. <strong>Keep the module docked</strong> until it finishes.
                </li>
                <li>
                  After a restart the left half sometimes does not reconnect to the computer. If
                  that happens, the window asks you to unplug its USB cable, count to ten and plug
                  it back in. It runs on its battery, so nothing is interrupted.
                </li>
              </ul>
            </Notice>
          </>
        )}

        {/* --- running, and the verdict ------------------------------------------------------ */}
        {(running || verdict) && (
          <>
            {replug ? (
              <Notice tone="err" icon="warn" className="fw-replug"
                title="Unplug the left half's USB cable, count to ten, and plug it back in">
                The left half restarted and has not come back to the computer. It is powered by its
                battery, so this is not a power cycle and nothing being written is interrupted. This
                message goes away as soon as it is back.
              </Notice>
            ) : running && (
              <Notice tone="warn" title="Keep the module docked">
                <span className="flash-spinner" aria-hidden="true" />
                {currentLabel(rows)}
                {mine?.elapsedMs != null && (
                  <span className="fw-elapsed"> · {duration(mine.elapsedMs)} so far</span>
                )}
              </Notice>
            )}

            <ol className="fw-steps">
              {rows.map((r) => (
                <li key={r.key}
                  className={["fw-step", r.failed ? "is-failed" : r.done ? "is-done" : "is-running"].join(" ")}>
                  <span className="fw-step-mark" aria-hidden="true">
                    {r.failed ? "!" : r.done ? "✓" : "…"}
                  </span>
                  <span className="fw-step-label">{r.label}</span>
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
              <Notice tone={verdict.ok ? "ok" : "err"}
                title={verdict.ok ? "Module firmware written and verified" : "The update stopped before it finished"}>
                {verdict.summary}
                {verdict.failures?.length > 0 && (
                  <ul className="fw-verdict-list">
                    {verdict.failures.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                )}
                {verdict.advisories?.length > 0 && (
                  <ul className="fw-verdict-list">
                    {verdict.advisories.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                )}
                <p className="fw-verdict-note">
                  Saved as <code>{mine?.id}</code>. Keep it if anything looked wrong.
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
