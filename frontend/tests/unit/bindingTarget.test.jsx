// The strip over the Modules palette: what is selected, what it holds, and the x that clears
// it (only when there is something to clear).
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BindingTarget from "../../src/components/modules/BindingTarget";

const labelFor = (c) => c;

describe("BindingTarget", () => {
  it("asks for a gesture when nothing is selected", () => {
    render(<BindingTarget selectedBinding={null} name="" labelFor={labelFor} onDone={() => {}} onClear={() => {}} />);
    expect(screen.getByText("Select a gesture above to bind it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear this binding" })).toBeNull();
  });

  it("names the gesture and its binding, and the x clears it", () => {
    const onClear = vi.fn();
    render(<BindingTarget selectedBinding={{ id: 1, actionCode: "F21" }} name="tap"
      labelFor={labelFor} onDone={() => {}} onClear={onClear} />);
    expect(screen.getByText("tap")).toBeInTheDocument();
    expect(screen.getByText("F21")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear this binding" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("offers no x on an unbound gesture, and says motion for an empty axis half", () => {
    const { rerender } = render(<BindingTarget selectedBinding={{ id: 1, actionCode: "" }} name="tap"
      labelFor={labelFor} onDone={() => {}} onClear={() => {}} />);
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Clear|motion/ })).toBeNull();
    rerender(<BindingTarget selectedBinding={{ axisHalf: { behavior: "x", side: "-" }, actionCode: "", unsetText: "motion" }}
      name="scroll · left" labelFor={labelFor} onDone={() => {}} onClear={() => {}} />);
    expect(screen.getByText("motion")).toBeInTheDocument();
    rerender(<BindingTarget selectedBinding={{ axisHalf: { behavior: "x", side: "-" }, actionCode: "F16", unsetText: "motion" }}
      name="scroll · left" labelFor={labelFor} onDone={() => {}} onClear={() => {}} />);
    expect(screen.getByRole("button", { name: "Back to motion" })).toBeInTheDocument();
  });
});
