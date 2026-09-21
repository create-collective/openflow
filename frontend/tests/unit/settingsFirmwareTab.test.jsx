// The Firmware tab notices a keyboard plugged in AFTER it was opened.
//
// The tab used to take one reading when it was switched to, and nothing refetched afterwards.
// Open Settings, plug the keyboard in, and "Update firmware" stayed disabled saying "Connect the
// keyboard first" with the keyboard sitting there connected (owner, 2026-09-21). The device
// stream is already open for the whole app and reports a half within a tick, so the tab paints
// from that instead of taking a reading of its own.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const stream = { data: null };

vi.mock("../../src/lib/deviceStream", () => ({
  useDeviceStream: () => stream,
  useFlashProgress: () => ({ run: null, events: [] }),
  seedFlashProgress: () => {},
  subscribeDeviceStream: () => () => {},
  getDeviceStream: () => stream,
}));

vi.mock("../../src/lib/api", () => ({
  BASE: "http://localhost",
  api: {
    settings: async () => ({ groups: [] }),
    systemInfo: async () => ({ backendVersion: "0.3.0", os: "Windows", arch: "AMD64" }),
    firmwareCatalog: async () => ({ reference: { createFirmware: "3.41.0", moduleFirmware: "2.3.3" }, images: [] }),
    status: async () => ({ halves: [] }),
    backups: async () => ({ backups: [], dir: "" }),
    deviceLog: async () => ({ entries: [] }),
    recoveryOps: async () => ({ ops: [] }),
  },
}));

const half = (extra = {}) => ({
  side: "left", port: "COM25", description: "Create Left", connected: true,
  firmwareVersion: "3.41.0", keyboardId: 0, ...extra,
});

let Settings;
beforeEach(async () => {
  stream.data = null;
  ({ default: Settings } = await import("../../src/pages/Settings"));
});
afterEach(() => vi.clearAllMocks());

async function openFirmwareTab() {
  render(<Settings />);
  await screen.findByRole("tab", { name: /firmware/i });
  await userEvent.click(screen.getByRole("tab", { name: /firmware/i }));
}

describe("Settings → Firmware", () => {
  it("offers nothing to flash while no half is connected", async () => {
    await openFirmwareTab();
    const btn = await screen.findByRole("button", { name: /update keyboard firmware/i });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/Connect the keyboard to read device firmware versions/i)).toBeInTheDocument();
  });

  it("enables as soon as the stream reports a half, with no tab change", async () => {
    const { rerender } = render(<Settings />);
    await screen.findByRole("tab", { name: /firmware/i });
    await userEvent.click(screen.getByRole("tab", { name: /firmware/i }));
    expect(await screen.findByRole("button", { name: /update keyboard firmware/i })).toBeDisabled();

    // The keyboard is plugged in while the tab sits open: the next tick of the stream carries it.
    stream.data = { status: { halves: [half()] } };
    rerender(<Settings />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /update keyboard firmware/i })).toBeEnabled());
    expect(screen.getByRole("button", { name: /update keyboard firmware/i }))
      .toHaveAttribute("title", "Update the firmware the keyboard halves run");
    // And the half it found is named, with what it runs.
    expect(screen.getByText("Create Left firmware")).toBeInTheDocument();
  });

  it("is about the keyboard only: OpenFlow's own version and links live on About", async () => {
    stream.data = { status: { halves: [half()] } };
    await openFirmwareTab();
    await screen.findByText("Firmware library");
    expect(screen.queryByRole("button", { name: /check openflow for updates/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /create companion/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /about/i }));
    expect(await screen.findByRole("button", { name: /check openflow for updates/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /firmware ↗/i })).toBeInTheDocument();
    // The About tab says nothing about the board.
    expect(screen.queryByText("Firmware library")).not.toBeInTheDocument();
  });
});
