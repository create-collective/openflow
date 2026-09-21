// The firmware library: the catalogue, and what of it this machine holds.
//
// OpenFlow ships neither the images nor an excuse. Every version in the list can be downloaded,
// whole -- both sides, both flash generations, because which of the four a half takes is decided
// from its product id at flash time and holding three of them is how that decision fails later.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FirmwareLibrary, { heldByVersion, megabytes } from "../../src/components/FirmwareLibrary";
import { api } from "../../src/lib/api";

// Two catalogued versions as the Software page's summary sees them.
const CATALOGUE = [
  { file: "kb_fwl.bin", target: "keyboard", component: "left", generation: "A", version: "3.41.0",
    versionLabel: "3.41.0", versionConfidence: "declared", bundle: "NayaFlow 1.25.1",
    bundles: ["v1.25.1"], releaseOrder: 23, flashable: true, sha256: "aaaa" },
  { file: "kb_fwr.bin", target: "keyboard", component: "right", generation: "A", version: "3.41.0",
    versionLabel: "3.41.0", versionConfidence: "declared", bundle: "NayaFlow 1.25.1",
    bundles: ["v1.25.1"], releaseOrder: 23, flashable: true, sha256: "bbbb" },
  { file: "kb_fwl.bin", target: "keyboard", component: "left", generation: "A", version: "3.35.4",
    versionLabel: "3.35.4", versionConfidence: "declared", bundle: "NayaFlow 1.21.0",
    bundles: ["v1.21.0"], releaseOrder: 20, flashable: true, sha256: "cccc" },
];

const MB = 663552;
const holding = (present) => [
  { path: "v1.25.1/kb_fwl.bin", version: "3.41.0", bytes: MB, present: present.includes("3.41.0") },
  { path: "v1.25.1/kb_fwr.bin", version: "3.41.0", bytes: MB, present: present.includes("3.41.0") },
  { path: "v1.21.0/kb_fwl.bin", version: "3.35.4", bytes: MB, present: present.includes("3.35.4") },
];

const library = (present = [], extra = {}) => ({
  dir: "C:/Users/x/AppData/Roaming/OpenFlow/firmware",
  source: { url: "https://example.test/fw", authenticated: false, private: false },
  images: holding(present),
  ...extra,
});

beforeEach(() => {
  vi.spyOn(api, "firmwareLibrary").mockResolvedValue(library([]));
});
afterEach(() => vi.restoreAllMocks());

describe("heldByVersion", () => {
  it("counts what is held against what the version needs", () => {
    const held = heldByVersion([
      { version: "3.41.0", bytes: 10, present: true },
      { version: "3.41.0", bytes: 10, present: false },
      { version: "3.35.4", bytes: 10, present: true },
    ]);
    expect(held["3.41.0"]).toEqual({ held: 1, total: 2, bytes: 20 });
    expect(held["3.35.4"]).toEqual({ held: 1, total: 1, bytes: 10 });
  });

  it("reports sizes in a unit a person can weigh a download in", () => {
    expect(megabytes(663552 * 4)).toBe("2.5 MB");
  });
});

describe("FirmwareLibrary", () => {
  it("offers to download everything missing, with what it will cost", async () => {
    render(<FirmwareLibrary images={CATALOGUE} />);
    const all = await screen.findByRole("button", { name: /download all/i });
    expect(all).toHaveTextContent("Download all (2 versions, 1.9 MB)");
  });

  it("downloads one version whole, and says so afterwards", async () => {
    const fetchSpy = vi.spyOn(api, "fetchFirmware").mockImplementation(async () => {
      api.firmwareLibrary.mockResolvedValue(library(["3.41.0"]));
      return { requested: 2, fetched: 2, failed: 0, images: [] };
    });
    render(<FirmwareLibrary images={CATALOGUE} />);
    const row = (await screen.findAllByRole("button", { name: /^download \(/i }))[0];
    await userEvent.click(row);

    expect(fetchSpy).toHaveBeenCalledWith(["3.41.0"]);
    // Held now, so the button becomes a statement rather than an offer.
    expect(await screen.findByText("Downloaded")).toBeInTheDocument();
    expect(screen.getByText(/2 images downloaded/i)).toBeInTheDocument();
  });

  it("does not claim success when a file did not arrive", async () => {
    vi.spyOn(api, "fetchFirmware").mockResolvedValue({
      requested: 2, fetched: 1, failed: 1,
      images: [{ ok: true, path: "v1.25.1/kb_fwl.bin" },
               { ok: false, path: "v1.25.1/kb_fwr.bin", reason: "what arrived does not match the catalogue" }],
    });
    render(<FirmwareLibrary images={CATALOGUE} />);
    await userEvent.click((await screen.findAllByRole("button", { name: /^download \(/i }))[0]);
    expect(await screen.findByText(/1 downloaded, 1 failed/i)).toBeInTheDocument();
    expect(screen.getByText(/does not match the catalogue/i)).toBeInTheDocument();
  });

  it("warns when the archive is private before anyone presses anything", async () => {
    api.firmwareLibrary.mockResolvedValue(
      library([], { source: { url: "https://example.test/fw", authenticated: false, private: true } }));
    render(<FirmwareLibrary images={CATALOGUE} />);
    expect(await screen.findByText(/archive is private/i)).toBeInTheDocument();
    expect(screen.getByText("OPENFLOW_FIRMWARE_TOKEN")).toBeInTheDocument();
  });

  it("does not claim everything is downloaded when it could not find out", async () => {
    // The backend answering 404 (an older build, a restart mid-session) left the button saying
    // "All versions downloaded" -- the most confident possible claim from no information.
    api.firmwareLibrary.mockRejectedValue(new Error("Not Found"));
    render(<FirmwareLibrary images={CATALOGUE} />);
    const btn = await screen.findByRole("button", { name: /checking what is downloaded/i });
    expect(btn).toBeDisabled();
    expect(screen.queryByText(/all versions downloaded/i)).not.toBeInTheDocument();
  });

  it("says nothing is left to download once everything is held", async () => {
    api.firmwareLibrary.mockResolvedValue(library(["3.41.0", "3.35.4"]));
    render(<FirmwareLibrary images={CATALOGUE} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /all versions downloaded/i })).toBeDisabled());
  });
});
