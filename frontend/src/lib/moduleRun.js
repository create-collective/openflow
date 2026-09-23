// The module firmware dialog's decisions, kept out of the component so they can be tested.
//
// A module update (backend device/module_procedure.py) runs on the same run registry and the same
// progress stream as a keyboard flash; its run ids start with "module-". Two things are specific
// to it and are decided here:
//
//   * the REPLUG. After a restart the left half sometimes never comes back on USB until its cable
//     is unplugged and plugged in again (measured 2026-09-23; it runs on its battery, so this is
//     not a power cycle). The procedure logs a `replug` event with phase `action` when it has not
//     seen the half for 30 s, and `ok` when it is back. While one is open the dialog says so in
//     the largest words it has: this is the one step that needs the person at the keyboard.
//   * what BLOCKS a start. The backend's plan returns every precondition as {code, text}; Force
//     Update lifts the ones about a module that does not identify (plan.forceLifts), never the
//     others -- a Track stays refused, the right half must still be unplugged.

export const isModuleRun = (run) => !!run && String(run.id || "").startsWith("module-");

/** The open replug request, or null. Cleared by the half coming back, or by the run ending. */
export function replugPending(events) {
  let pending = null;
  for (const e of events || []) {
    if (e.step === "replug" && e.phase === "action") pending = e;
    else if (e.step === "replug" && e.phase === "ok") pending = null;
    else if (pending && e.phase === "ok"
      && (e.step === "bundle.restart" || e.step === "module.restart" || e.step === "mcuboot.exit")) {
      pending = null;
    }
    if (e.step === "run.end") pending = null;
  }
  return pending;
}

/** The blockers that stop this start. "not-downloaded" is a button, not a blocker. */
export function activeBlockers(plan, force) {
  const lifted = new Set(force ? plan?.forceLifts || [] : []);
  return (plan?.blockers || []).filter((b) => b.code !== "not-downloaded" && !lifted.has(b.code));
}

/** What the start button says, and whether there is anything to do at all. */
export function startLabel(plan, { force = false, forceType = "" } = {}) {
  const t = plan?.target;
  if (!t) return { label: "Update module", needed: false };
  const kind = plan?.module?.type && plan.module.type.indexOf("Unknown") !== 0
    ? plan.module.type : "module";
  if (force) return { label: `Force update as ${forceType} to ${t.version}`, needed: true };
  if (t.unchanged) return { label: `Already on ${t.version}`, needed: false };
  if (t.downgrade) return { label: `Downgrade ${kind} to ${t.version}`, needed: true };
  return { label: `Update ${kind} to ${t.version}`, needed: true };
}
