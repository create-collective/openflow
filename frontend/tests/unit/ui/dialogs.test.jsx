// confirmDialog() resolves the way the person answered; the Modal shell respects `dismissable`.
import { act, render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DialogHost from "../../../src/components/ui/ConfirmDialog";
import Modal from "../../../src/components/ui/Modal";
import { confirmDialog } from "../../../src/lib/dialogs";

// Synchronous act: confirmDialog() publishes its request synchronously, and the promise it
// returns must come back un-awaited (an async helper would flatten it and wait for the click).
function ask(options) {
  let promise;
  act(() => { promise = confirmDialog(options); });
  return promise;
}

describe("confirmDialog through the DialogHost", () => {
  it("resolves true on the confirming button, which carries the action's own label", async () => {
    render(<DialogHost />);
    const p = ask({ title: "Clear slot 3?", message: "The host is forgotten.", confirmLabel: "Clear and pair", tone: "danger" });
    expect(screen.getByRole("dialog", { name: "Clear slot 3?" })).toBeInTheDocument();
    expect(screen.getByText("The host is forgotten.")).toBeInTheDocument();
    const yes = screen.getByRole("button", { name: "Clear and pair" });
    expect(yes).toHaveClass("ui-btn-danger");
    await act(async () => { fireEvent.click(yes); });
    await expect(p).resolves.toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("resolves false on Cancel, on Escape and on the backdrop, and Cancel has the focus", async () => {
    render(<DialogHost />);
    let p = ask({ title: "Restore?" });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancel" })); });
    await expect(p).resolves.toBe(false);

    p = ask({ title: "Restore?" });
    await act(async () => { fireEvent.keyDown(document, { key: "Escape" }); });
    await expect(p).resolves.toBe(false);

    p = ask({ title: "Restore?" });
    await act(async () => { fireEvent.mouseDown(document.querySelector(".ui-modal-backdrop")); });
    await expect(p).resolves.toBe(false);
  });

  it("a second request cancels the first", async () => {
    render(<DialogHost />);
    const first = ask({ title: "One?" });
    const second = ask({ title: "Two?" });
    await expect(first).resolves.toBe(false);
    expect(screen.getByRole("dialog", { name: "Two?" })).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Confirm" })); });
    await expect(second).resolves.toBe(true);
  });
});

describe("Modal", () => {
  it("ignores Escape and the backdrop while not dismissable, and closes otherwise", () => {
    const onClose = vi.fn();
    const { rerender } = render(<Modal open title="Flashing…" onClose={onClose} dismissable={false}>body</Modal>);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(document.querySelector(".ui-modal-backdrop"));
    expect(onClose).not.toHaveBeenCalled();
    rerender(<Modal open title="Flashed" onClose={onClose}>body</Modal>);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.mouseDown(document.querySelector(".ui-modal-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
