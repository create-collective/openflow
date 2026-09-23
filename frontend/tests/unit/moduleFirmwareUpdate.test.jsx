// The module firmware dialog (owner, 2026-09-23): read the board, say what stops an update in
// plain words, offer the versions this keyboard can take, start the procedure, and -- while it
// runs -- ask for the cable replug the moment the backend asks for one.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ModuleFirmwareUpdate from "../../src/components/ModuleFirmwareUpdate";
import { api } from "../../src/lib/api";
import { resetFlashProgressForTests, seedFlashProgress } from "../../src/lib/deviceStream";

const READY = {
  flashEnabled: true, keyboardFirmware: "3.41.0", storedBundle: "2.3.2", rightConnected: false,
  module: { type: "Touch", address: 16, docked: "left", firmwareVersion: "2.3.2" },
  versions: [
    { version: "2.3.3", fits: true, needsKeyboard: "3.40.0", present: true, historyPath: "v1.25.1/module/FlashMemory.bin" },
    { version: "2.3.2", fits: true, needsKeyboard: "3.31.1", present: true, historyPath: "v1.21.0/module/FlashMemory.bin" },
  ],
  target: { version: "2.3.3", present: true, upload: true, program: true, downgrade: false, unchanged: false },
  blockers: [], forceTypes: ["Touch", "Tune"], forceLifts: ["no-module", "unknown-module"],
};

async function openIt(plan = READY) {
  vi.spyOn(api, "moduleUpdatePlan").mockResolvedValue(plan);
  render(<ModuleFirmwareUpdate connected />);
  await userEvent.click(screen.getByRole("button", { name: /update module firmware/i }));
}

beforeEach(() => {
  resetFlashProgressForTests();
  vi.spyOn(api, "flashRun").mockResolvedValue({ run: null });
});
afterEach(() => vi.restoreAllMocks());

describe("ModuleFirmwareUpdate", () => {
  it("offers the newest version this keyboard can take, and starts it", async () => {
    const flash = vi.spyOn(api, "flashModuleFirmware").mockResolvedValue({ id: "module-1", running: true, events: [] });
    await openIt();
    const go = await screen.findByRole("button", { name: "Update Touch to 2.3.3" });
    expect(go).toBeEnabled();
    await userEvent.click(go);
    expect(flash).toHaveBeenCalledWith({ version: "2.3.3", allow_older: false });
  });

  it("lists what stops it in plain words, and does not let it start", async () => {
    await openIt({ ...READY, rightConnected: true,
      blockers: [{ code: "right-connected", text: "Unplug the RIGHT half's USB cable." }] });
    expect(await screen.findByText("Unplug the RIGHT half's USB cable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update Touch to 2.3.3" })).toBeDisabled();
  });

  it("marks a downgrade, and a version the keyboard is too old for", async () => {
    await openIt({ ...READY,
      versions: [{ ...READY.versions[0], fits: false }, READY.versions[1]],
      target: { ...READY.target, version: "2.3.2", downgrade: true } });
    expect(await screen.findByText(/older module firmware than it runs now/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /2.3.3 · needs keyboard 3.40.0 or newer/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Downgrade Touch to 2.3.2" })).toBeEnabled();
  });

  it("force-updates a module that does not identify, as the type the person names", async () => {
    const flash = vi.spyOn(api, "flashModuleFirmware").mockResolvedValue({ id: "module-2", running: true, events: [] });
    await openIt({ ...READY, module: { type: "Unknown (addr 0x4A)", address: 74, firmwareVersion: "2.3.3" },
      storedBundle: "2.3.3", target: { ...READY.target, unchanged: true },
      blockers: [{ code: "unknown-module", text: "The docked module does not identify as a known type." }] });
    expect(await screen.findByText(/does not identify as a known type/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /force update/i }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /the docked module is a/i }), "Tune");
    await userEvent.click(screen.getByRole("button", { name: "Force update as Tune to 2.3.3" }));
    expect(flash).toHaveBeenCalledWith({ version: "2.3.3", allow_older: false, force_type: "Tune" });
  });

  it("asks for the replug, large, while the run is waiting on it, and drops it when the half is back", async () => {
    await openIt();
    act(() => seedFlashProgress({ id: "module-3", running: true, events: [
      { seq: 1, step: "bundle.restart", phase: "start", label: "Waiting for the keyboard to restart" },
      { seq: 2, step: "replug", phase: "action", label: "Unplug", detail: "Unplug its USB cable" },
    ] }));
    expect(await screen.findByText(/count to ten, and plug it back in/i)).toBeInTheDocument();
    act(() => seedFlashProgress({ id: "module-3", running: true, events: [
      { seq: 3, step: "replug", phase: "ok", label: "Unplug", detail: "the left half is back" },
    ] }));
    expect(screen.queryByText(/count to ten, and plug it back in/i)).not.toBeInTheDocument();
  });

  it("ignores a KEYBOARD run on the same stream", async () => {
    await openIt();
    act(() => seedFlashProgress({ id: "flash-9", running: true, events: [
      { seq: 1, step: "upload", phase: "start", label: "Writing the firmware" }] }));
    expect(await screen.findByRole("button", { name: "Update Touch to 2.3.3" })).toBeInTheDocument();
  });
});
