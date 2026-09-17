// The shared profile plumbing: the active profile comes from (and goes to) the persisted key,
// deleting selects the first remaining profile, new and duplicate switch to the result, and a
// switch after a reload lands on the fresh list.
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const profiles = [
  { id: "p1", name: "One", layers: [{ id: "l1", orderId: 0, name: "Base", keys: [] }] },
  { id: "p2", name: "Two", layers: [{ id: "l2", orderId: 0, name: "Base", keys: [] }] },
];
const api = {
  userdata: vi.fn(async () => ({ profiles: profiles.map((p) => ({ ...p })) })),
  createProfile: vi.fn(async () => ({ id: "p3" })),
  duplicateProfile: vi.fn(async () => ({ id: "p4" })),
  deleteProfile: vi.fn(async () => ({})),
  renameProfile: vi.fn(async () => ({})),
};
vi.mock("../../src/lib/api", () => ({ api, BASE: "http://localhost:3001" }));

const { default: useProfileEditor } = await import("../../src/lib/useProfileEditor");
const { setActiveProfileId } = await import("../../src/lib/activeProfile");
const { _resetProfilesForTests } = await import("../../src/lib/profilesStore");

let last;
function Probe() {
  last = useProfileEditor();
  return <div>{last.profile ? last.profile.name : "none"}|{last.layer ? last.layer.id : "-"}</div>;
}

beforeEach(() => {
  _resetProfilesForTests();
  try { localStorage.removeItem("openflow.activeProfile"); } catch {}
  api.userdata.mockClear();
});

describe("useProfileEditor", () => {
  it("starts on the persisted profile and writes a switch back to it", async () => {
    localStorage.setItem("openflow.activeProfile", "p2");
    setActiveProfileId("p2");
    render(<Probe />);
    await waitFor(() => expect(screen.getByText("Two|l2")).toBeInTheDocument());
    act(() => { last.switchProfile("p1"); });
    await waitFor(() => expect(screen.getByText("One|l1")).toBeInTheDocument());
    expect(localStorage.getItem("openflow.activeProfile")).toBe("p1");
  });

  it("falls back to the first profile, and new / duplicate switch to what the backend returned", async () => {
    setActiveProfileId(null);
    render(<Probe />);
    await waitFor(() => expect(screen.getByText("One|l1")).toBeInTheDocument());
    profiles.push({ id: "p3", name: "New Profile", layers: [{ id: "l3", orderId: 0, name: "Base", keys: [] }] });
    await act(async () => { await last.profileHandlers.onNew(); });
    expect(api.createProfile).toHaveBeenCalledWith("New Profile");
    await waitFor(() => expect(screen.getByText("New Profile|l3")).toBeInTheDocument());
    expect(localStorage.getItem("openflow.activeProfile")).toBe("p3");
    profiles.pop();
  });

  it("delete clears the key and the first remaining profile takes over", async () => {
    setActiveProfileId("p2");
    render(<Probe />);
    await waitFor(() => expect(screen.getByText("Two|l2")).toBeInTheDocument());
    const removed = profiles.splice(1, 1);
    await act(async () => { await last.profileHandlers.onDelete("p2"); });
    expect(api.deleteProfile).toHaveBeenCalledWith("p2");
    await waitFor(() => expect(screen.getByText("One|l1")).toBeInTheDocument());
    expect(localStorage.getItem("openflow.activeProfile")).toBeNull();
    profiles.push(...removed);
  });

  it("fetches the profiles once for two subscribers", async () => {
    render(<><Probe /><Probe /></>);
    await waitFor(() => expect(screen.getAllByText("One|l1")).toHaveLength(2));
    expect(api.userdata).toHaveBeenCalledTimes(1);
  });
});
