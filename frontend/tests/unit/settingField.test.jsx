// A slider saves once, when it is let go (owner, 2026-09-25): Interface scaling saved on every
// step of the drag, the saves landed in any order, and coming back to the page showed a value
// that was never the one released on.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SettingField from "../../src/components/SettingField";

const SCALE = { id: "interface_scaling", label: "Interface scaling", kind: "slider",
  min: -500, max: 500, default: 0, value: 0, provenance: "app" };

describe("SettingField slider", () => {
  it("does not save while dragging, and saves the released value once", () => {
    const onChange = vi.fn();
    render(<SettingField f={SCALE} onChange={onChange} />);
    const range = screen.getByRole("slider");
    for (const v of [100, 250, 400, 500]) fireEvent.change(range, { target: { value: String(v) } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("spinbutton")).toHaveValue(500);   // the box follows the drag
    fireEvent.pointerUp(range);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("interface_scaling", 500);
  });

  it("commits a keyboard step on key up", () => {
    const onChange = vi.fn();
    render(<SettingField f={SCALE} onChange={onChange} />);
    const range = screen.getByRole("slider");
    fireEvent.change(range, { target: { value: "-500" } });
    fireEvent.keyUp(range, { key: "Home" });
    expect(onChange).toHaveBeenCalledWith("interface_scaling", -500);
  });

  it("releasing without moving saves nothing", () => {
    const onChange = vi.fn();
    render(<SettingField f={SCALE} onChange={onChange} />);
    fireEvent.pointerUp(screen.getByRole("slider"));
    expect(onChange).not.toHaveBeenCalled();
  });
});
