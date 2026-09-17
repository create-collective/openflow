// In-app confirmation, in place of the browser's built-in confirm box.
//
// confirmDialog({ title, message, detail, confirmLabel, cancelLabel, tone }) resolves true when
// the person confirms and false when they cancel, press Escape or click outside. One request at
// a time: a second ask settles the first as cancelled. The DialogHost mounted once in App.jsx
// renders whatever is pending, so callers stay as simple as the native call they replace:
//
//     if (!(await confirmDialog({ title: "Clear slot 3?", message: "..." }))) return;
//
// Why not the browser's own box: it is unstyled, un-themable, blocks the event loop, cannot be
// told apart from a site prompt, and in the desktop app is a bare OS dialog with no context.
import { useSyncExternalStore } from "react";

let pending = null;
const listeners = new Set();

function emit() {
  for (const l of listeners) l();
}

export function confirmDialog(options) {
  return new Promise((resolve) => {
    if (pending) pending.resolve(false);
    pending = {
      id: Date.now(),
      confirmLabel: "Confirm",
      cancelLabel: "Cancel",
      tone: "default",
      ...options,
      resolve,
    };
    emit();
  });
}

/** Settle the pending request (the host calls this from its buttons). */
export function settleDialog(result) {
  if (!pending) return;
  const request = pending;
  pending = null;
  emit();
  request.resolve(!!result);
}

export function getPendingDialog() {
  return pending;
}

export function subscribeDialogs(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePendingDialog() {
  return useSyncExternalStore(subscribeDialogs, getPendingDialog, () => null);
}
