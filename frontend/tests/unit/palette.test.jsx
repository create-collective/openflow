// The action palette's head: the categories as icon + label pills with the search after them,
// the target it writes to, and the virtual keyboard with F1-F24 on one row.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ActionPalette from "../../src/components/ActionPalette";

const catalog = {
  tabs: [
    { id: "basic", label: "B", title: "Basic keys", contexts: ["key", "module"],
      categories: [{ name: "Letters", actions: [{ code: "A", label: "A", actionType: "key", name: "A" }] }] },
    { id: "layers", label: "✦", title: "Layers", contexts: ["key"], categories: [] },
  ],
  names: {},
  layerActionTypes: [],
  shortcuts: {},
};

describe("ActionPalette", () => {
  it("labels the categories, says what a pick writes to, and puts the search in the head", () => {
    render(<ActionPalette catalog={catalog} assigning="A → Hold" onPick={() => {}} />);
    for (const name of ["Keyboard", "Basic", "Layers", "Macros"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("tab", { name: "Keyboard" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Assigning:")).toHaveTextContent("Assigning: A → Hold");
    const search = screen.getByRole("searchbox", { name: "Search all actions" });
    expect(search.closest(".palette-head")).not.toBeNull();
  });

  it("shows F1 to F24 on the keyboard and picks through the modifiers", () => {
    const onPick = vi.fn();
    render(<ActionPalette catalog={catalog} onPick={onPick} />);
    expect(screen.getByRole("button", { name: "F1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "F13" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "F24" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "F24" }));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ actionCode: "F24" }));
  });

  it("with the Mac relabel on, F21-F24 are not bindable; F20 still is", () => {
    const onPick = vi.fn();
    render(<ActionPalette catalog={catalog} onPick={onPick} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Mac" }));
    for (const f of ["F21", "F22", "F23", "F24"]) {
      expect(screen.getByRole("button", { name: f })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "F20" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "F24" }));
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Mac" }));
    expect(screen.getByRole("button", { name: "F24" })).toBeEnabled();
  });

  it("without a target, a category tab says to select a key first", () => {
    render(<ActionPalette catalog={catalog} disabled onPick={() => {}} />);
    fireEvent.click(screen.getByRole("tab", { name: "Basic" }));
    expect(screen.getByText("Select a key on the map first.")).toBeInTheDocument();
  });
});
