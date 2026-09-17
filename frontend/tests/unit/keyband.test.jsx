// The selected-key band: the key's legend and half, one card per behaviour with what it does,
// the card the palette writes to marked, a bound card clearable, the slot still to come
// disabled, and nothing selectable until a key is.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SelectedKeyPanel from "../../src/components/SelectedKeyPanel";

const slots = [
  { id: "tap", label: "Tap", enabled: true },
  { id: "hold", label: "Hold", enabled: true },
  { id: "double_tap", label: "Double Tap", enabled: true },
  { id: "tap_hold", label: "Tap + Hold", enabled: true },
  { id: "double_tap+hold", label: "Double Tap + Hold", enabled: false },
];
const card = (label) => screen.getByText(label, { selector: ".keyband-card-label" }).closest("button");

describe("SelectedKeyPanel", () => {
  it("shows the key and its behaviours as cards, with the active slot marked", () => {
    const onSelectSlot = vi.fn();
    const onClearSlot = vi.fn();
    render(
      <SelectedKeyPanel
        label="LC2"
        bindings={{ tap: { actionCode: "A", actionType: "key" }, hold: { actionCode: "LSHIFT", actionType: "key" } }}
        slots={slots}
        activeSlot="hold"
        onSelectSlot={onSelectSlot}
        onClearSlot={onClearSlot}
      />
    );
    expect(screen.getByText("LC2 · Left half")).toBeInTheDocument();

    const hold = card("Hold");
    expect(hold).toHaveAttribute("aria-pressed", "true");
    expect(within(hold).getByText("Selected")).toBeInTheDocument();
    expect(card("Tap")).toHaveAttribute("aria-pressed", "false");
    expect(within(card("Tap")).getByText("A")).toBeInTheDocument();
    expect(within(card("Double Tap")).getByText("Unassigned")).toBeInTheDocument();

    fireEvent.click(card("Tap"));
    expect(onSelectSlot).toHaveBeenCalledWith("tap");

    fireEvent.click(screen.getByRole("button", { name: "Clear Hold" }));
    expect(onClearSlot).toHaveBeenCalledWith("hold");
    expect(screen.queryByRole("button", { name: "Clear Double Tap" })).not.toBeInTheDocument();

    const soon = card("Double Tap + Hold");
    expect(soon).toBeDisabled();
    expect(within(soon).getByText("soon")).toBeInTheDocument();
  });

  it("with no key selected, says so and offers nothing to pick", () => {
    render(<SelectedKeyPanel label={null} slots={slots} activeSlot="tap" onSelectSlot={() => {}} onClearSlot={() => {}} />);
    expect(screen.getByText("No key selected")).toBeInTheDocument();
    expect(screen.getByText("Select one on the map.")).toBeInTheDocument();
    for (const s of slots) expect(card(s.label)).toBeDisabled();
  });
});
