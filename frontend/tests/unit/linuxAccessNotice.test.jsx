// Linux without OpenFlow's udev rule: the backend attaches the fix to a half's status, and the
// Hub shows it once with the commands to paste. Nothing shows when no half carries one.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LinuxAccessNotice, { accessFix } from "../../src/components/LinuxAccessNotice";

const FIX = {
  kind: "linux-udev-rule",
  port: "/dev/ttyACM0",
  ruleFile: "70-openflow.rules",
  commands: "printf '%s\\n' 'rule one' 'rule two' | sudo tee /etc/udev/rules.d/70-openflow.rules >/dev/null\nsudo udevadm control --reload-rules\nsudo udevadm trigger --subsystem-match=tty",
};

afterEach(() => vi.restoreAllMocks());

describe("accessFix", () => {
  it("finds the fix on whichever half carries it", () => {
    const halves = [
      { side: "left", connected: true },
      { side: "right", connected: false, error: "Linux denied access", fix: FIX },
    ];
    expect(accessFix(halves)).toBe(FIX);
  });

  it("is null for ordinary disconnects, no halves, and no status at all", () => {
    expect(accessFix([{ side: "left", connected: false, error: "no longer on the USB bus" }])).toBeNull();
    expect(accessFix([])).toBeNull();
    expect(accessFix(undefined)).toBeNull();
  });

  it("ignores a fix it does not know how to show", () => {
    expect(accessFix([{ side: "left", fix: { kind: "something-else" } }])).toBeNull();
  });
});

describe("LinuxAccessNotice", () => {
  it("renders nothing without a fix", () => {
    const { container } = render(<LinuxAccessNotice fix={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says what is wrong and shows the commands verbatim", () => {
    const { container } = render(<LinuxAccessNotice fix={FIX} />);
    expect(screen.getByText("Linux is not letting OpenFlow open the keyboard")).toBeInTheDocument();
    expect(container.querySelector("pre.access-fix-cmd").textContent).toBe(FIX.commands);
  });

  it("copies the commands and says so", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<LinuxAccessNotice fix={FIX} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy commands" })); });
    expect(writeText).toHaveBeenCalledWith(FIX.commands);
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("falls back to selecting by hand when the clipboard is out of reach", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => { throw new Error("denied"); }) } });
    render(<LinuxAccessNotice fix={FIX} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy commands" })); });
    expect(screen.getByText(/Select the commands and copy them instead/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
