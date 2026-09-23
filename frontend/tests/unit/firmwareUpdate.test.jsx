// The firmware update dialog: what it offers, and what it shows while a run is going
// (SCRUM-104), plus the two pure pieces behind it -- how a run's events are accumulated from the
// stream, and how they become rows.
//
// The behaviour worth pinning is the honesty: a version whose image is not on this machine is
// not offerable, a downgrade says it is one, and while the flash runs the dialog cannot be
// dismissed and says not to unplug the keyboard. All three exist because of what a real run
// looks like: minutes long, with the half dark and silent in the middle of it.
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FirmwareUpdate, { currentLabel, stepRows } from "../../src/components/FirmwareUpdate";
import { mergeFlash, resetFlashProgressForTests, seedFlashProgress } from "../../src/lib/deviceStream";
import { api } from "../../src/lib/api";

const PLAN = {
  flashEnabled: true,
  imagesDir: "C:/firmware",
  halves: [
    { side: "left", port: "COM30", mode: "app", generation: "A", currentVersion: "3.41.0" },
    { side: "right", port: "COM29", mode: "app", generation: "A", currentVersion: "3.41.0" },
  ],
  versions: [
    { version: "3.41.0", declared: true, bundle: "NayaFlow 1.25.1", sides: ["left", "right"] },
    { version: "3.35.4", declared: true, bundle: "NayaFlow 1.21.0", sides: ["left", "right"] },
    { version: "NayaFlow 1.3.8 to 1.6.10", declared: false, bundle: "NayaFlow 1.6.10",
      sides: ["left", "right"] },
  ],
  targets: {
    left: { side: "left", image: "v1.25.1/kb_fwl.bin", file: "kb_fwl.bin", generation: "A",
            version: "3.41.0", present: true, reason: null, currentVersion: "3.41.0",
            downgrade: false, unchanged: true },
    right: { side: "right", image: "v1.25.1/kb_fwr.bin", file: "kb_fwr.bin", generation: "A",
             version: "3.41.0", present: true, reason: null, currentVersion: "3.41.0",
             downgrade: false, unchanged: true },
  },
};

// The ordinary state of a fresh install: the catalogue knows the version, the machine has not
// downloaded it. Not an error -- a button.
const NOT_DOWNLOADED = {
  ...PLAN,
  source: { url: "https://example.test/fw", authenticated: false },
  targets: {
    left: { side: "left", image: "v1.25.1/kb_fwl.bin", file: "kb_fwl.bin", generation: "A",
            version: "3.41.0", present: false, fetchable: true, currentVersion: "3.35.4",
            reason: "v1.25.1/kb_fwl.bin has not been downloaded yet", downgrade: false,
            unchanged: false },
    right: { side: "right", image: "v1.25.1/kb_fwr.bin", file: "kb_fwr.bin", generation: "A",
             version: "3.41.0", present: false, fetchable: true, currentVersion: "3.35.4",
             reason: "v1.25.1/kb_fwr.bin has not been downloaded yet", downgrade: false,
             unchanged: false },
  },
};

const DOWNLOADED = {
  ...NOT_DOWNLOADED,
  targets: {
    left: { ...NOT_DOWNLOADED.targets.left, present: true, fetchable: false, reason: null },
    right: { ...NOT_DOWNLOADED.targets.right, present: true, fetchable: false, reason: null },
  },
};

const OLDER = {
  ...PLAN,
  targets: {
    left: { side: "left", image: "v1.21.0/kb_fwl.bin", file: "kb_fwl.bin", generation: "A",
            version: "3.35.4", present: true, reason: null, currentVersion: "3.41.0",
            downgrade: true, unchanged: false },
    right: { side: "right", image: "v1.21.0/kb_fwr.bin", file: "kb_fwr.bin", generation: "A",
             version: "3.35.4", present: false, currentVersion: "3.41.0",
             reason: "v1.21.0/kb_fwr.bin is not in the image tree", downgrade: true,
             unchanged: false },
  },
};

function ev(seq, step, phase, extra = {}) {
  return { seq, step, phase, label: step, ...extra };
}

beforeEach(() => {
  resetFlashProgressForTests();
  vi.spyOn(api, "firmwareUpdatePlan").mockResolvedValue(PLAN);
  vi.spyOn(api, "flashRun").mockResolvedValue({ run: null });
});
afterEach(() => vi.restoreAllMocks());

describe("mergeFlash", () => {
  it("appends only what the client has not seen", () => {
    let s = mergeFlash({ run: null, events: [] },
                       { id: "flash-1", running: true, seq: 2, events: [ev(1, "a", "ok"), ev(2, "b", "start")] });
    expect(s.events.map((e) => e.step)).toEqual(["a", "b"]);
    s = mergeFlash(s, { id: "flash-1", running: true, seq: 3, events: [ev(3, "c", "ok")] });
    expect(s.events.map((e) => e.step)).toEqual(["a", "b", "c"]);
  });

  it("ignores a replay of events it already holds", () => {
    // A reconnected stream replays from the start; the run is the same one, so the list must not
    // double up.
    const first = mergeFlash({ run: null, events: [] },
                             { id: "flash-1", seq: 2, events: [ev(1, "a", "ok"), ev(2, "b", "ok")] });
    const again = mergeFlash(first, { id: "flash-1", seq: 2, events: [ev(1, "a", "ok"), ev(2, "b", "ok")] });
    expect(again.events).toHaveLength(2);
  });

  it("starts fresh for a different run", () => {
    const first = mergeFlash({ run: null, events: [] }, { id: "flash-1", seq: 1, events: [ev(1, "a", "ok")] });
    const second = mergeFlash(first, { id: "flash-2", seq: 1, events: [ev(1, "z", "start")] });
    expect(second.events.map((e) => e.step)).toEqual(["z"]);
  });
});

describe("stepRows", () => {
  it("keeps one row per step and half, in the order they were reached", () => {
    const rows = stepRows([
      ev(1, "run.start", "ok"),
      ev(2, "preflight.capture", "start"),
      ev(3, "preflight.capture", "ok", { took_ms: 1200 }),
      ev(4, "upload", "start", { side: "left" }),
      ev(5, "upload", "progress", { side: "left", percent: 40 }),
      ev(6, "upload", "progress", { side: "left", percent: 55 }),
    ]);
    expect(rows.map((r) => r.step)).toEqual(["preflight.capture", "upload"]);
    expect(rows[0].done).toBe(true);
    expect(rows[0].tookMs).toBe(1200);
    expect(rows[1].percent).toBe(55);
    expect(rows[1].done).toBeUndefined();
    expect(rows[1].side).toBe("left");
  });

  it("does not let a later note turn a failed step green", () => {
    const rows = stepRows([
      ev(1, "verify.compare", "start"),
      ev(2, "verify.compare", "fail", { detail: "the LED map differs" }),
      ev(3, "verify.compare", "note", { detail: "brightness was restored" }),
    ]);
    expect(rows[0].failed).toBe(true);
    expect(rows[0].done).toBeUndefined();
  });

  it("the headline is the step that has started and not finished", () => {
    const rows = stepRows([
      ev(1, "preflight.capture", "ok"),
      ev(2, "upload", "start", { side: "left", label: "Writing the firmware" }),
    ]);
    expect(currentLabel(rows)).toBe("Writing the firmware");
  });
});

describe("FirmwareUpdate", () => {
  it("is disabled until a keyboard is connected", () => {
    render(<FirmwareUpdate connected={false} />);
    expect(screen.getByRole("button", { name: /update keyboard firmware/i })).toBeDisabled();
  });

  it("names the file each half would take, and how long the whole thing takes", async () => {
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");
    expect(screen.getByText("kb_fwl.bin")).toBeInTheDocument();
    expect(screen.getByText("kb_fwr.bin")).toBeInTheDocument();
    expect(screen.getByText(/goes dark/i)).toBeInTheDocument();
    expect(screen.getByText(/Do not unplug the keyboard/i)).toBeInTheDocument();
    // Both halves already run this version, so nothing is ticked and Flash stays off.
    expect(screen.getByRole("button", { name: /flash 3\.41\.0/i })).toBeDisabled();
  });

  it("says when a version is a downgrade, and refuses to offer an image it does not hold", async () => {
    // The plan is re-resolved per version: picking the older one is what turns these two halves
    // into "one downgrade we can do, one image we do not have".
    api.firmwareUpdatePlan.mockImplementation(async (v) => (v === "3.35.4" ? OLDER : PLAN));
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");
    await userEvent.selectOptions(screen.getByRole("combobox"), "3.35.4");
    await screen.findByText(/writes an older firmware/i);
    // The right half's image is missing: its checkbox cannot be ticked and the row says why.
    expect(screen.getByLabelText(/Right half/i)).toBeDisabled();
    expect(screen.getByText(/not in the image tree/i)).toBeInTheDocument();
    // The left one is offerable, so the action is live -- and it says it is a downgrade.
    expect(screen.getByRole("button", { name: /downgrade to 3\.35\.4/i })).toBeEnabled();
  });

  it("offers to download a version this machine does not hold, then lets it be flashed", async () => {
    // Images are not shipped with OpenFlow, so "we do not have it" is the normal first state and
    // has to be recoverable from inside the dialog rather than being a dead end.
    let downloaded = false;
    api.firmwareUpdatePlan.mockImplementation(async () => (downloaded ? DOWNLOADED : NOT_DOWNLOADED));
    const fetchSpy = vi.spyOn(api, "fetchFirmware").mockImplementation(async () => {
      downloaded = true;
      return { requested: 2, fetched: 2, failed: 0, images: [] };
    });

    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText(/^3\.41\.0 has not been downloaded yet$/);
    expect(screen.getByLabelText(/Left half/i)).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /download 3\.41\.0/i }));
    await waitFor(() => expect(screen.getByLabelText(/Left half/i)).toBeEnabled());
    expect(fetchSpy).toHaveBeenCalledWith({ versions: ["3.41.0"] });
    expect(screen.queryByText(/^3\.41\.0 has not been downloaded yet$/)).not.toBeInTheDocument();
  });

  it("says which files did not arrive rather than claiming the download worked", async () => {
    api.firmwareUpdatePlan.mockResolvedValue(NOT_DOWNLOADED);
    vi.spyOn(api, "fetchFirmware").mockResolvedValue({
      requested: 2, fetched: 1, failed: 1,
      images: [{ ok: true, path: "v1.21.0/kb_fwl.bin" },
               { ok: false, path: "v1.21.0/kb_fwr.bin", reason: "what arrived does not match the catalogue" }],
    });

    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText(/^3\.41\.0 has not been downloaded yet$/);
    await userEvent.click(screen.getByRole("button", { name: /download 3\.41\.0/i }));
    expect(await screen.findByText(/1 of 2 file\(s\) did not arrive/i)).toBeInTheDocument();
    expect(screen.getByText(/does not match the catalogue/i)).toBeInTheDocument();
  });

  it("cannot be dismissed while the flash runs, and shows the steps as they arrive", async () => {
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");

    act(() => seedFlashProgress({
      id: "flash-20260921-101500", running: true, sides: ["left"], elapsedMs: 65000, seq: 2,
      events: [{ seq: 1, step: "preflight.capture", phase: "ok", label: "Backing up what is on the keyboard", took_ms: 4000 },
               { seq: 2, step: "slot.erase", phase: "start", side: "left", label: "Preparing the flash (this takes a few seconds)" }],
      verdict: null,
    }));

    expect(await screen.findByText("Updating keyboard firmware…")).toBeInTheDocument();
    expect(screen.getByText("Backing up what is on the keyboard")).toBeInTheDocument();
    // Twice, deliberately: as the headline of what is happening now, and as a row in the list.
    expect(screen.getAllByText(/Preparing the flash/)).toHaveLength(2);
    expect(screen.getByText(/1m 05s so far/)).toBeInTheDocument();
    // Escape does nothing: there is nothing to go back to, and hiding the run is the worst
    // thing this dialog could do.
    await userEvent.keyboard("{Escape}");
    expect(screen.getByText("Updating keyboard firmware…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });

  it("ends with a verdict that names the log", async () => {
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");

    act(() => seedFlashProgress({
      id: "flash-20260921-101500", running: false, sides: ["left"], elapsedMs: 253000, seq: 1,
      events: [{ seq: 1, step: "version.confirm", phase: "ok", side: "left", label: "Restarting and confirming the new version", took_ms: 120000 }],
      verdict: { ok: true, summary: "firmware written and verified; the keyboard matches its backup",
                 failures: [], advisories: [] },
    }));

    expect(await screen.findByText("Keyboard firmware updated ✓")).toBeInTheDocument();
    expect(screen.getByText(/matches its backup/)).toBeInTheDocument();
    expect(screen.getByText("flash-20260921-101500")).toBeInTheDocument();
  });

  it("reopened after a finished flash, offers the next one rather than the old verdict", async () => {
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");
    const done = { id: "flash-20260923-170000", running: false, sides: ["left"], elapsedMs: 1000, seq: 1,
      events: [{ seq: 1, step: "version.confirm", phase: "ok", side: "left", label: "Confirming", took_ms: 1 }],
      verdict: { ok: true, summary: "firmware written and verified", failures: [], advisories: [] } };
    act(() => seedFlashProgress(done));
    expect(await screen.findByText("Keyboard firmware updated ✓")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    vi.spyOn(api, "flashRun").mockResolvedValue({ run: done });   // the backend still holds it
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    expect(await screen.findByText("Left half")).toBeInTheDocument();
    expect(screen.queryByText("Keyboard firmware updated ✓")).not.toBeInTheDocument();
  });

  it("does not draw a MODULE run's steps as a keyboard flash", async () => {
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");
    act(() => seedFlashProgress({ id: "module-20260923-161251", running: true, seq: 1,
      events: [{ seq: 1, step: "upload", phase: "start", label: "Writing the firmware" }] }));
    expect(screen.queryByText("Updating keyboard firmware…")).not.toBeInTheDocument();
    expect(screen.getByText("Left half")).toBeInTheDocument();
  });

  it("a failure says the keyboard is probably fine and points at the log", async () => {
    render(<FirmwareUpdate connected />);
    await userEvent.click(screen.getByRole("button", { name: /update keyboard firmware/i }));
    await screen.findByText("Left half");

    act(() => seedFlashProgress({
      id: "flash-20260921-110000", running: false, sides: ["left"], elapsedMs: 42000, seq: 1,
      events: [{ seq: 1, step: "identify", phase: "fail", side: "left", label: "Confirming which half this is", detail: "neither port answered" }],
      verdict: { ok: false, summary: "UploadRefused: neither port answered",
                 failures: ["neither port answered"], advisories: [] },
    }));

    expect(await screen.findByText("The firmware run did not finish")).toBeInTheDocument();
    expect(screen.getByText(/still fine/i)).toBeInTheDocument();

    vi.spyOn(api, "flashLog").mockResolvedValue({ id: "flash-20260921-110000", text: "10:00  !! Confirming which half this is" });
    await userEvent.click(screen.getByRole("button", { name: /view the log/i }));
    await waitFor(() => expect(screen.getByText(/!! Confirming which half this is/)).toBeInTheDocument());
  });
});
