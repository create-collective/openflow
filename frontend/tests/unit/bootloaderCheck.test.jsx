// "Check what it runs" on the Information page's bootloader banner: a read-only look at a half
// sitting in MCUboot (/api/recovery-read). No real half is ever in the bootloader on CI, so the
// answers are the endpoint's three shapes, mocked.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const recoveryRead = vi.fn();
vi.mock("../../src/lib/api", () => ({ api: { recoveryRead: (...a) => recoveryRead(...a) } }));

import BootloaderCheck from "../../src/components/BootloaderCheck";

describe("BootloaderCheck", () => {
  it("names each image the half holds against the catalogue", async () => {
    recoveryRead.mockResolvedValueOnce({
      state: "ok", port: "COM7", pidSide: "right",
      images: [
        { slot: 0, active: true, confirmed: true, version: "3.41.0", hash: "aa", identified: true, side: "right", versionLabel: "3.41.0" },
        { slot: 1, active: false, confirmed: false, version: "9.0.0", hash: "bb", identified: false },
      ],
    });
    render(<BootloaderCheck />);
    await userEvent.click(screen.getByRole("button", { name: "Check what it runs" }));
    expect(await screen.findByText(/COM7, a right half holds 2 firmware images/)).toBeInTheDocument();
    expect(screen.getByText(/Slot 0: Create Right 3\.41\.0 · running · confirmed/)).toBeInTheDocument();
    expect(screen.getByText(/Slot 1: version 9\.0\.0, an image OpenFlow does not hold/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("says so when no half is in the bootloader any more", async () => {
    recoveryRead.mockResolvedValueOnce({ state: "none", detail: "No half is in MCUboot recovery." });
    render(<BootloaderCheck />);
    await userEvent.click(screen.getByRole("button", { name: "Check what it runs" }));
    expect(await screen.findByText(/No half is in the bootloader now/)).toBeInTheDocument();
  });

  it("shows the refusal while a flash is running", async () => {
    recoveryRead.mockImplementationOnce(() => Promise.reject(new Error("A firmware flash is running; check again once it has finished.")));
    render(<BootloaderCheck />);
    await userEvent.click(screen.getByRole("button", { name: "Check what it runs" }));
    expect(await screen.findByText(/Could not read it: A firmware flash is running/)).toBeInTheDocument();
  });
});
