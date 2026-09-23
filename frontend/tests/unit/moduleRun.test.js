// The module dialog's decisions (src/lib/moduleRun.js): when to ask for a replug, what blocks a
// start, and what the start button says.
import { describe, expect, it } from "vitest";
import { activeBlockers, isModuleRun, replugPending, startLabel } from "../../src/lib/moduleRun.js";

const ev = (step, phase, extra = {}) => ({ step, phase, ...extra });

describe("replugPending", () => {
  it("is the open request, from the moment the run asks until the half is back", () => {
    const asked = ev("replug", "action", { detail: "Unplug its USB cable" });
    expect(replugPending([ev("bundle.restart", "start"), asked])).toBe(asked);
    expect(replugPending([asked, ev("replug", "ok")])).toBeNull();
    // the half coming back ends it even if the ok line is not there
    expect(replugPending([asked, ev("module.restart", "ok")])).toBeNull();
    expect(replugPending([asked, ev("run.end", "fail")])).toBeNull();
  });

  it("asks again for the second restart", () => {
    const first = ev("replug", "action", { seq: 1 });
    const second = ev("replug", "action", { seq: 9 });
    expect(replugPending([first, ev("replug", "ok"), ev("module.restart", "start"), second])).toBe(second);
  });
});

describe("activeBlockers", () => {
  const plan = {
    forceLifts: ["no-module", "unknown-module"],
    blockers: [{ code: "unknown-module", text: "does not identify" },
      { code: "right-connected", text: "unplug the right half" },
      { code: "not-downloaded", text: "not downloaded" }],
  };

  it("keeps everything but the download, which is a button", () => {
    expect(activeBlockers(plan, false).map((b) => b.code)).toEqual(["unknown-module", "right-connected"]);
  });

  it("lets Force Update lift only what it exists for", () => {
    expect(activeBlockers(plan, true).map((b) => b.code)).toEqual(["right-connected"]);
    const track = { forceLifts: plan.forceLifts, blockers: [{ code: "track", text: "no Track" }] };
    expect(activeBlockers(track, true).map((b) => b.code)).toEqual(["track"]);
  });
});

describe("startLabel", () => {
  const plan = (target, type = "Touch") => ({ module: { type }, target: { version: "2.3.2", ...target } });

  it("names the module and says upgrade, downgrade or nothing to do", () => {
    expect(startLabel(plan({}))).toEqual({ label: "Update Touch to 2.3.2", needed: true });
    expect(startLabel(plan({ downgrade: true }))).toEqual({ label: "Downgrade Touch to 2.3.2", needed: true });
    expect(startLabel(plan({ unchanged: true }))).toEqual({ label: "Already on 2.3.2", needed: false });
  });

  it("says what a forced run will program, and never calls an unknown module by its type string", () => {
    expect(startLabel(plan({ unchanged: true }, "Unknown (addr 0x4A)"), { force: true, forceType: "Tune" }))
      .toEqual({ label: "Force update as Tune to 2.3.2", needed: true });
    expect(startLabel(plan({}, "Unknown (addr 0x4A)")).label).toBe("Update module to 2.3.2");
  });
});

it("tells a module run from a keyboard run by its id", () => {
  expect(isModuleRun({ id: "module-20260923-160051" })).toBe(true);
  expect(isModuleRun({ id: "flash-20260922-101618" })).toBe(false);
  expect(isModuleRun(null)).toBe(false);
});
