// Module firmware is its own button because it is its own procedure (owner, 2026-09-21).
//
// The keyboard flash swaps an MCUboot slot: the old image stays put until the new one has been
// written and its hash checked, so a failure changes nothing. A module bundle is a LittleFS
// filesystem written into the left half's modules partition — no slot, no swap, nothing to roll
// back to. It has never been run on hardware, and the dialog's job is to say so plainly rather
// than to be a greyed-out button with no explanation.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ModuleFirmwareUpdate from "../../src/components/ModuleFirmwareUpdate";
import { api } from "../../src/lib/api";

const LIBRARY = {
  dir: "C:/fw",
  source: { url: "https://example.test/fw", authenticated: false },
  images: [
    { path: "v1.21.0/module/FlashMemory.bin", target: "module", label: "2.3.3", present: true },
    { path: "v1.20.0/module/FlashMemory.bin", target: "module", label: "2.3.2", present: false },
    { path: "v1.25.1/kb_fwl.bin", target: "keyboard", label: "3.41.0", present: true },
  ],
};

beforeEach(() => {
  vi.spyOn(api, "firmwareLibrary").mockResolvedValue(LIBRARY);
});
afterEach(() => vi.restoreAllMocks());

describe("ModuleFirmwareUpdate", () => {
  it("is a separate button from the keyboard's", () => {
    render(<ModuleFirmwareUpdate />);
    expect(screen.getByRole("button", { name: /update module firmware/i })).toBeEnabled();
  });

  it("says the write path has never been run, and why that matters here", async () => {
    render(<ModuleFirmwareUpdate />);
    await userEvent.click(screen.getByRole("button", { name: /update module firmware/i }));

    expect(await screen.findByText(/Writing module firmware is not enabled/i)).toBeInTheDocument();
    expect(screen.getByText(/never been run on hardware/i)).toBeInTheDocument();
    // The reason it is treated differently, not just the fact that it is.
    expect(screen.getByText(/partly erased/i)).toBeInTheDocument();
    expect(screen.getByText(/keeps working/i)).toBeInTheDocument();
    // And it does not offer to do it anyway.
    expect(screen.queryByRole("button", { name: /^flash/i })).not.toBeInTheDocument();
  });

  it("shows what is docked and what it runs", async () => {
    render(<ModuleFirmwareUpdate
      modules={[{ side: "left", type: "Tune", firmwareVersion: "2.1.2" }]}
      reference="2.3.3" />);
    await userEvent.click(screen.getByRole("button", { name: /update module firmware/i }));
    expect(await screen.findByText("Tune on the left half")).toBeInTheDocument();
    expect(screen.getByText("2.1.2")).toBeInTheDocument();
    expect(screen.getByText("Naya ships (reference)")).toBeInTheDocument();
  });

  it("counts the bundles held, because downloading one is allowed even though flashing is not", async () => {
    render(<ModuleFirmwareUpdate />);
    await userEvent.click(screen.getByRole("button", { name: /update module firmware/i }));
    // Two module bundles catalogued, one held — and the keyboard image is not counted.
    expect(await screen.findByText(/1 of 2 module bundles downloaded/i)).toBeInTheDocument();
  });

  it("says nothing is docked rather than showing an empty list", async () => {
    render(<ModuleFirmwareUpdate modules={[]} />);
    await userEvent.click(screen.getByRole("button", { name: /update module firmware/i }));
    expect(await screen.findByText(/No module is docked/i)).toBeInTheDocument();
  });
});
