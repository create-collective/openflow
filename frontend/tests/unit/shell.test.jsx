// The shell: the nav carries the five pages and a More menu with the app pages; the theme
// switch sets an explicit preference; the profile bar shows the active profile, both halves,
// and reads the keyboard into the profile it produced.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const profiles = [
  { id: "p1", name: "One", layers: [{ id: "l1", orderId: 0, name: "Base", keys: [] }] },
  { id: "p2", name: "Two", layers: [{ id: "l2", orderId: 0, name: "Base", keys: [] }] },
];
const api = {
  userdata: vi.fn(async () => ({ profiles: profiles.map((p) => ({ ...p })) })),
  readKeyboard: vi.fn(),
  createBackup: vi.fn(async () => ({})),
  deviceState: vi.fn(async () => null),
};
vi.mock("../../src/lib/api", () => ({ api, BASE: "http://localhost:3001" }));

let stream = { data: null, connected: true };
vi.mock("../../src/lib/deviceStream", () => ({ useDeviceStream: () => stream }));

const { default: TopNav } = await import("../../src/components/shell/TopNav");
const { default: ThemeToggle } = await import("../../src/components/shell/ThemeToggle");
const { default: ProfileBar } = await import("../../src/components/shell/ProfileBar");
const { getActiveProfileId, setActiveProfileId } = await import("../../src/lib/activeProfile");
const { _resetProfilesForTests } = await import("../../src/lib/profilesStore");
const { _resetDeviceActionsForTests } = await import("../../src/lib/deviceActions");
const { setThemePreference } = await import("../../src/lib/theme");

beforeEach(() => {
  _resetProfilesForTests();
  _resetDeviceActionsForTests();
  setActiveProfileId(null);
  api.readKeyboard.mockReset();
  stream = { data: null, connected: true };
});

describe("TopNav", () => {
  it("links the five pages and keeps the app pages under More", () => {
    render(<MemoryRouter initialEntries={["/settings"]}><TopNav /></MemoryRouter>);
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const [label, href] of [
      ["Bindings", "/layer-management"], ["LED Map", "/colormapping"],
      ["Modules", "/module-configuration"], ["Macros", "/macro"], ["Devices", "/information"],
    ]) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(screen.getByRole("link", { name: /OpenFlow/ })).toHaveAttribute("href", "/");
    expect(nav).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    const more = screen.getByRole("button", { name: /More/ });
    expect(more).toHaveClass("active"); // Settings lives under More
    fireEvent.click(more);
    const menu = screen.getByRole("menu", { name: "More" });
    expect(menu).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Hub" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveClass("active");
    expect(screen.getByRole("menuitem", { name: "Bug Report" })).toHaveAttribute("href", "/bug-report");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("ThemeToggle", () => {
  it("sets an explicit preference for the other theme and remembers it", () => {
    setThemePreference("dark");
    render(<ThemeToggle />);
    const b = screen.getByRole("button", { name: "Switch to the light theme" });
    fireEvent.click(b);
    expect(localStorage.getItem("openflow.theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to the dark theme" })).toBeInTheDocument();
    setThemePreference("system");
  });
});

describe("ProfileBar", () => {
  it("shows the active profile, both halves, and reads the keyboard into the profile it produced", async () => {
    stream = {
      connected: true,
      data: { status: { halves: [
        { side: "left", connected: true, batteryPercent: 80 },
        { side: "right", connected: true, batteryPercent: 15, module: { type: "TOUCH", batteryPercent: 50 } },
      ] } },
    };
    setActiveProfileId("p2");
    render(<MemoryRouter><ProfileBar /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Two")).toBeInTheDocument());
    expect(screen.getByText("L")).toBeInTheDocument();
    expect(screen.getByText("R")).toBeInTheDocument();
    expect(screen.getByText("TOUCH")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Back up/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Flash to keyboard/ })).toBeInTheDocument();

    profiles.push({ id: "p9", name: "Read 1", layers: [{ id: "l9", orderId: 0, name: "Base", keys: [] }] });
    api.readKeyboard.mockResolvedValue({ profileId: "p9", bindings: 7, layers: 1, warnings: [] });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Read from keyboard/ })); });
    await waitFor(() => expect(screen.getByText("Read 1")).toBeInTheDocument());
    expect(getActiveProfileId()).toBe("p9");
    expect(screen.getByText(/7 binding\(s\) across 1 layer\(s\)/)).toBeInTheDocument();
    profiles.pop();
  });

  it("says when the backend is offline instead of showing halves", async () => {
    stream = { connected: false, data: null };
    render(<MemoryRouter><ProfileBar /></MemoryRouter>);
    expect(screen.getByText("Backend offline")).toBeInTheDocument();
    expect(screen.queryByText("L")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("One")).toBeInTheDocument());
  });
});
