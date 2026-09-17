// The module-profile card under the layers: one row per bay with the profile the layer arms,
// marked live when the board runs it and base when inherited; a row opens that profile on
// the Modules page.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModuleProfileList from "../../src/components/ModuleProfileList";

const bays = {
  layerLabel: "Layer 1 Num Pad",
  profilesFor: (type, side) => ({
    "track:left": [{ id: "tl", name: "Naya Track Left", onBoard: true }],
    "track:right": [{ id: "tr", name: "Naya Track Right", onBoard: false }],
    "touch:null": [{ id: "to", name: "Naya Touch Windows", onBoard: false }],
    "tune:null": [],
  })[`${type}:${side}`] || [],
  selectedFor: (type, side) => ({ "track:left": "tl", "track:right": "disabled", "touch:null": "to", "tune:null": null })[`${type}:${side}`],
  inheritedFor: (type) => type === "touch",
  onManage: vi.fn(),
};

describe("ModuleProfileList", () => {
  it("lists each bay's profile with its marks", () => {
    render(<ModuleProfileList bays={bays} boardKnown />);
    expect(screen.getByText("For Layer 1 Num Pad")).toBeInTheDocument();
    const left = screen.getByRole("button", { name: /Track · left/ });
    expect(within(left).getByText("Naya Track Left")).toBeInTheDocument();
    expect(within(left).getByText("live")).toBeInTheDocument();
    expect(within(left).queryByText(/base/)).not.toBeInTheDocument();
    expect(left).not.toHaveClass("pending");
    const right = screen.getByRole("button", { name: /Track · right/ });
    expect(within(right).getByText("Disabled")).toBeInTheDocument();
    const touch = screen.getByRole("button", { name: /Touch/ });
    expect(within(touch).getByText("Naya Touch Windows")).toBeInTheDocument();
    expect(within(touch).getByText(/base/)).toBeInTheDocument();
    expect(touch).toHaveClass("pending"); // selected, but the board is not running it
    const tune = screen.getByRole("button", { name: /Tune/ });
    expect(within(tune).getByText("Not set")).toBeInTheDocument();
    fireEvent.click(tune);
    expect(bays.onManage).toHaveBeenCalledWith("tune", null);
  });

  it("marks nothing as pending until the board has been read", () => {
    render(<ModuleProfileList bays={bays} />);
    expect(screen.getByRole("button", { name: /Touch/ })).not.toHaveClass("pending");
  });

  it("renders nothing before the bay data exists", () => {
    const { container } = render(<ModuleProfileList bays={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
