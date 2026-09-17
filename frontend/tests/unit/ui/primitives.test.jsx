// The primitives behave: the right classes for the right props, disabled when busy, tabs move
// with the keyboard, a toggle is a switch, an empty key/value row renders nothing.
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Badge from "../../../src/components/ui/Badge";
import Button from "../../../src/components/ui/Button";
import Card from "../../../src/components/ui/Card";
import IconButton from "../../../src/components/ui/IconButton";
import { KVRow } from "../../../src/components/ui/KV";
import Notice from "../../../src/components/ui/Notice";
import SettingRow from "../../../src/components/ui/SettingRow";
import Tabs from "../../../src/components/ui/Tabs";
import Toggle from "../../../src/components/ui/Toggle";

describe("Button", () => {
  it("carries variant, size and done as classes and is a plain button by default", () => {
    render(<Button variant="primary" size="sm" done>Go</Button>);
    const b = screen.getByRole("button", { name: "Go" });
    expect(b).toHaveClass("ui-btn", "ui-btn-primary", "ui-btn-sm", "ui-btn-done");
    expect(b).toHaveAttribute("type", "button");
  });
  it("is disabled while busy and reports pressed", () => {
    const onClick = vi.fn();
    render(<Button busy pressed onClick={onClick}>Read</Button>);
    const b = screen.getByRole("button", { name: "Read" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("IconButton", () => {
  it("names itself by its title", () => {
    render(<IconButton title="Layer options" reveal>⋯</IconButton>);
    const b = screen.getByRole("button", { name: "Layer options" });
    expect(b).toHaveClass("ui-iconbtn", "ui-iconbtn-reveal");
  });
});

describe("Badge", () => {
  it("keeps the label and carries the tone", () => {
    render(<Badge tone="ok" size="xs">verified</Badge>);
    expect(screen.getByText("verified")).toHaveClass("ui-badge-ok", "ui-badge-xs");
  });
});

describe("Tabs", () => {
  const items = [{ id: "a", label: "A" }, { id: "b", label: "B", disabled: true }, { id: "c", label: "C" }];
  it("is a tablist that selects on click and skips disabled tabs with the arrows", () => {
    const onChange = vi.fn();
    render(<Tabs items={items} value="a" onChange={onChange} variant="segmented" />);
    expect(screen.getByRole("tablist")).toHaveClass("ui-tabs-segmented");
    expect(screen.getByRole("tab", { name: "A" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "C" }));
    expect(onChange).toHaveBeenLastCalledWith("c");
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("c");   // from a: b is disabled, so c
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("c");
  });
});

describe("Toggle", () => {
  it("is a switch that reports the next value", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="LED scan mode" />);
    const s = screen.getByRole("switch", { name: "LED scan mode" });
    expect(s).toHaveAttribute("aria-checked", "false");
    fireEvent.click(s);
    expect(onChange).toHaveBeenCalledWith(true);
  });
  it("as a check is a labelled checkbox", () => {
    const onChange = vi.fn();
    render(<Toggle variant="check" checked onChange={onChange} label="Keep my timing" />);
    const c = screen.getByRole("checkbox", { name: "Keep my timing" });
    expect(c).toBeChecked();
    fireEvent.click(c);
    expect(onChange).toHaveBeenCalledWith(false);
  });
});

describe("KVRow", () => {
  it("renders nothing for an empty value and the value otherwise", () => {
    const { container } = render(<KVRow k="Firmware" v={undefined} />);
    expect(container).toBeEmptyDOMElement();
    render(<KVRow k="Port" v="COM6" layout="grid" />);
    expect(screen.getByText("COM6")).toHaveClass("ui-kv-v", "mono");
    expect(screen.getByText("Port").parentElement).toHaveClass("ui-kv-grid");
  });
});

describe("Card and Notice and SettingRow", () => {
  it("card titles and ruled heads, a notice's tone and dismiss, a setting's reset", () => {
    const onDismiss = vi.fn();
    const onReset = vi.fn();
    render(
      <>
        <Card title="Backend">body</Card>
        <Card title="Left" head={<span className="dot ok" />} actions={<Badge>left</Badge>} />
        <Notice tone="warn" size="sm" onDismiss={onDismiss}>stale</Notice>
        <SettingRow label="Tapping term" desc="How long" changed onReset={onReset} control={<span>ctl</span>} />
      </>,
    );
    expect(screen.getByRole("heading", { name: "Backend" }).parentElement).toHaveClass("ui-card");
    expect(screen.getByRole("heading", { name: "Left" }).parentElement).toHaveClass("ui-card-head");
    expect(screen.getByText("stale").closest(".ui-notice")).toHaveClass("ui-notice-warn", "ui-notice-sm");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Reset/ }));
    expect(onReset).toHaveBeenCalled();
  });
});
