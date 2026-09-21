// The firmware library: the catalogue, and what of it this machine holds.
//
// OpenFlow ships neither the images nor an excuse. Every version in the list can be downloaded,
// whole -- both sides, both flash generations, because which of the four a half takes is decided
// from its product id at flash time and holding three of them is how that decision fails later.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FirmwareLibrary, { heldByLabel, megabytes } from "../../src/components/FirmwareLibrary";
import { api } from "../../src/lib/api";

// The catalogue as the Firmware page's summary sees it: keyboard images, a module bundle,
// an image from a release that declared no version, and a userapp with no file of its own.
const CATALOGUE = [
  { file: "kb_fwl.bin", target: "keyboard", component: "left", generation: "A", version: "3.41.0",
    versionLabel: "3.41.0", versionConfidence: "declared", bundle: "NayaFlow 1.25.1",
    bundles: ["v1.25.1"], releaseOrder: 23, flashable: true, sha256: "aaaa",
    historyPath: "v1.25.1/kb_fwl.bin" },
  { file: "kb_fwr.bin", target: "keyboard", component: "right", generation: "A", version: "3.41.0",
    versionLabel: "3.41.0", versionConfidence: "declared", bundle: "NayaFlow 1.25.1",
    bundles: ["v1.25.1"], releaseOrder: 23, flashable: true, sha256: "bbbb",
    historyPath: "v1.25.1/kb_fwr.bin" },
  { file: "kb_fwl.bin", target: "keyboard", component: "left", generation: "A", version: "3.35.4",
    versionLabel: "3.35.4", versionConfidence: "declared", bundle: "NayaFlow 1.21.0",
    bundles: ["v1.21.0"], releaseOrder: 20, flashable: true, sha256: "cccc",
    historyPath: "v1.21.0/kb_fwl.bin" },
  // Withheld from FLASHING, and still part of the archive: the module bundle, and an image from
  // a release that declared no version number at all.
  { file: "FlashMemory.bin", target: "module", component: "modules", version: "2.3.3",
    versionLabel: "2.3.3", versionConfidence: "declared", bundle: "NayaFlow 1.21.0",
    bundles: ["v1.21.0"], releaseOrder: 20, flashable: false, sha256: "dddd",
    withheldBecause: ["the modules slot is unconfirmed"],
    historyPath: "v1.21.0/module/FlashMemory.bin" },
  { file: "kb_fwl.bin", target: "keyboard", component: "left", version: null,
    versionLabel: "NayaFlow 1.3.8 to 1.6.10", versionConfidence: "inferred",
    bundle: "NayaFlow 1.6.10", bundles: ["v1.6.10"], releaseOrder: 8, flashable: true,
    sha256: "eeee", historyPath: "v1.6.10/kb_fwl.bin" },
  // Extracted from the bundle: no file of its own, so nothing to download separately.
  { file: "touch.sfb", target: "module", component: "touch", container: "FlashMemory.bin",
    version: "2.3.3", versionLabel: "2.3.3", versionConfidence: "declared",
    bundle: "NayaFlow 1.21.0", bundles: ["v1.21.0"], releaseOrder: 20, flashable: false,
    sha256: "ffff", historyPath: null },
];

const MB = 663552;
const holding = (present) => [
  { path: "v1.25.1/kb_fwl.bin", label: "3.41.0", bytes: MB, flashable: true, present: present.includes("3.41.0") },
  { path: "v1.25.1/kb_fwr.bin", label: "3.41.0", bytes: MB, flashable: true, present: present.includes("3.41.0") },
  { path: "v1.21.0/kb_fwl.bin", label: "3.35.4", bytes: MB, flashable: true, present: present.includes("3.35.4") },
  { path: "v1.21.0/module/FlashMemory.bin", label: "2.3.3", bytes: MB, flashable: false, present: present.includes("2.3.3") },
  { path: "v1.6.10/kb_fwl.bin", label: "NayaFlow 1.3.8 to 1.6.10", bytes: MB, flashable: true,
    present: present.includes("old") },
];

const library = (present = [], extra = {}) => ({
  dir: "C:/Users/x/AppData/Roaming/OpenFlow/firmware",
  source: { url: "https://example.test/fw", authenticated: false },
  images: holding(present),
  ...extra,
});

beforeEach(() => {
  vi.spyOn(api, "firmwareLibrary").mockResolvedValue(library([]));
});
afterEach(() => vi.restoreAllMocks());

describe("heldByLabel", () => {
  it("counts what is held against what each version needs", () => {
    const present = {};
    for (const row of holding(["3.41.0"])) present[row.path] = row;
    const held = heldByLabel(CATALOGUE, present);
    expect(held["3.41.0"]).toMatchObject({ held: 2, total: 2, missing: [] });
    expect(held["3.35.4"]).toMatchObject({ held: 0, total: 1 });
  });

  it("keys on how a version is NAMED, not on a version number", () => {
    // Everything before 1.14.5 shipped in releases that declared no firmware version. Keying on
    // the number dropped every one of them from the library, which is most of the archive.
    const held = heldByLabel(CATALOGUE, {});
    expect(held["NayaFlow 1.3.8 to 1.6.10"]).toMatchObject({ total: 1 });
  });

  it("ignores an entry that has no file of its own", () => {
    // touch.sfb is extracted from FlashMemory.bin; there is nothing to fetch for it separately.
    const held = heldByLabel(CATALOGUE, {});
    expect(held["2.3.3"].paths).toEqual(["v1.21.0/module/FlashMemory.bin"]);
  });

  it("reports sizes in a unit a person can weigh a download in", () => {
    expect(megabytes(663552 * 4)).toBe("2.5 MB");
  });
});

describe("FirmwareLibrary", () => {
  it("offers to download everything missing, with what it will cost", async () => {
    render(<FirmwareLibrary images={CATALOGUE} />);
    const all = await screen.findByRole("button", { name: /download all/i });
    // Four versions, five files: the two keyboard versions, the module bundle that is withheld
    // from flashing but still part of the archive, and the release-span image.
    expect(all).toHaveTextContent("Download all (4 versions, 3.2 MB)");
  });

  it("downloads one version whole, and says so afterwards", async () => {
    const fetchSpy = vi.spyOn(api, "fetchFirmware").mockImplementation(async () => {
      api.firmwareLibrary.mockResolvedValue(library(["3.41.0"]));
      return { requested: 2, fetched: 2, failed: 0, images: [] };
    });
    render(<FirmwareLibrary images={CATALOGUE} />);
    const row = (await screen.findAllByRole("button", { name: /^download \(/i }))[0];
    await userEvent.click(row);

    expect(fetchSpy).toHaveBeenCalledWith({ paths: ["v1.25.1/kb_fwl.bin", "v1.25.1/kb_fwr.bin"] });
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

  it("offers the module bundle, which is withheld from flashing but still part of the archive", async () => {
    // Downloadable and flashable are different questions. Filtering the library on "flashable"
    // left the module bundles, the dongle image and two pre-production keyboard images
    // unobtainable, with no reason on screen.
    const fetchSpy = vi.spyOn(api, "fetchFirmware").mockResolvedValue({ requested: 1, fetched: 1, failed: 0, images: [] });
    render(<FirmwareLibrary images={CATALOGUE} />);
    const groups = await screen.findAllByRole("button", { name: /^download \(/i });
    expect(groups).toHaveLength(4);
    await userEvent.click(groups[groups.length - 1]);
    expect(fetchSpy).toHaveBeenCalledWith({ paths: ["v1.21.0/module/FlashMemory.bin"] });
    // ...and the row still says it cannot be written to a keyboard.
    expect(screen.getAllByTitle(/modules slot is unconfirmed/i).length).toBeGreaterThan(0);
  });

  it("does not claim everything is downloaded when it could not find out", async () => {
    // The backend answering 404 (an older build, a restart mid-session) left the button saying
    // "All versions downloaded" -- the most confident possible claim from no information.
    api.firmwareLibrary.mockRejectedValue(new Error("Not Found"));
    render(<FirmwareLibrary images={CATALOGUE} />);
    const btn = await screen.findByRole("button", { name: /checking what is downloaded/i });
    expect(btn).toBeDisabled();
    expect(screen.queryByText(/everything downloaded/i)).not.toBeInTheDocument();
  });

  it("says nothing is left to download once everything is held", async () => {
    api.firmwareLibrary.mockResolvedValue(library(["3.41.0", "3.35.4", "2.3.3", "old"]));
    render(<FirmwareLibrary images={CATALOGUE} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /everything downloaded/i })).toBeDisabled());
  });
});
