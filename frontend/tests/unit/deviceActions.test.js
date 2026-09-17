// The read store behind the profile bar: a read reloads the profiles, makes the profile it
// produced the active one, tells the pages, marks the session and leaves a note; a read that
// found no keyboard says so and marks nothing; a backup is "saved" until the next edit.
import { beforeEach, describe, expect, it, vi } from "vitest";

const profiles = [{ id: "p1", name: "One", layers: [] }];
const api = {
  userdata: vi.fn(async () => ({ profiles: profiles.map((p) => ({ ...p })) })),
  readKeyboard: vi.fn(),
  createBackup: vi.fn(async () => ({})),
};
vi.mock("../../src/lib/api", () => ({ api, BASE: "http://localhost:3001" }));

const actions = await import("../../src/lib/deviceActions");
const { getActiveProfileId, setActiveProfileId } = await import("../../src/lib/activeProfile");
const { getProfiles, _resetProfilesForTests } = await import("../../src/lib/profilesStore");
const { getDeviceState } = await import("../../src/lib/deviceState");

beforeEach(() => {
  actions._resetDeviceActionsForTests();
  _resetProfilesForTests();
  setActiveProfileId(null);
  api.readKeyboard.mockReset();
  api.userdata.mockClear();
});

describe("readKeyboard", () => {
  it("reloads the profiles, switches to the read's profile, tells the pages, marks the session", async () => {
    profiles.push({ id: "p9", name: "Read 1", layers: [] });
    api.readKeyboard.mockResolvedValue({
      profileId: "p9", bindings: 12, layers: 2, warnings: [],
      modules: [{ uuid: "u1", type: "TOUCH" }], captured: [{ id: "c1" }],
    });
    const seen = [];
    const off = actions.onDeviceRead((r) => { seen.push(r.profileId); });
    expect(actions.hasReadDevice()).toBe(false);

    const r = await actions.readKeyboard();

    expect(r.profileId).toBe("p9");
    expect(api.userdata).toHaveBeenCalledTimes(1);
    expect(getProfiles().profiles.map((p) => p.id)).toEqual(["p1", "p9"]);
    expect(getActiveProfileId()).toBe("p9");
    expect(seen).toEqual(["p9"]);
    expect(actions.hasReadDevice()).toBe(true);
    expect(getDeviceState().modules).toEqual({ u1: { uuid: "u1", type: "TOUCH" } });
    const s = actions.getDeviceActions();
    expect(s.busy).toBeNull();
    expect(s.err).toBeNull();
    expect(s.justRead).toBe(true);
    expect(s.readNote.text).toBe("12 binding(s) across 2 layer(s) · captured 1 module profile(s) the board was running");
    expect(s.readNote.warnings).toBe(0);
    off();
    profiles.pop();
  });

  it("reports no keyboard on a 503 and marks nothing", async () => {
    api.readKeyboard.mockRejectedValue(new Error("503 No device found"));
    const listener = vi.fn();
    actions.onDeviceRead(listener);

    const r = await actions.readKeyboard();

    expect(r).toBeNull();
    expect(listener).not.toHaveBeenCalled();
    expect(actions.hasReadDevice()).toBe(false);
    expect(getActiveProfileId()).toBeNull();
    const s = actions.getDeviceActions();
    expect(s.busy).toBeNull();
    expect(s.err).toMatch(/No keyboard found/);
    expect(s.justRead).toBe(false);
    actions.clearDeviceError();
    expect(actions.getDeviceActions().err).toBeNull();
  });

  it("a page's failing follow-up does not undo the read", async () => {
    api.readKeyboard.mockResolvedValue({ profileId: "p1", bindings: 1, layers: 1 });
    actions.onDeviceRead(() => { throw new Error("page broke"); });
    const r = await actions.readKeyboard();
    expect(r.profileId).toBe("p1");
    expect(actions.hasReadDevice()).toBe(true);
    expect(actions.getDeviceActions().err).toBeNull();
  });
});

describe("backupNow", () => {
  it("is saved until the next edit clears it", async () => {
    await actions.backupNow();
    expect(api.createBackup).toHaveBeenCalledTimes(1);
    expect(actions.getDeviceActions().saved).toBeInstanceOf(Date);
    actions.clearSaved();
    expect(actions.getDeviceActions().saved).toBeNull();
  });
});
