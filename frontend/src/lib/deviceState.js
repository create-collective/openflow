// What we currently believe is ON the keyboard, shared across pages.
//
// A device read is expensive (it opens the COM port and walks every slot) and it is a
// whole-app fact, not one page's state. Keeping it in a component meant navigating to
// Bindings and back threw it away and the user had to read again to see which module
// profiles the board carries.
//
// It is deliberately NOT persisted to storage. Surviving a page reload would mean claiming
// knowledge of a keyboard we have not talked to since -- the board may have been unplugged,
// or flashed by NayaFlow. Losing it on reload is the honest behaviour; losing it on a route
// change was not.
//
// Invalidated by: another read (replaces it), a flash (we just changed the device), and the
// backend/device connection dropping.

let state = { modules: null, at: 0 };
const listeners = new Set();

function emit() {
  for (const l of listeners) l();
}

export function subscribeDeviceState(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getDeviceState() {
  return state;
}

/** Record a module read: { [moduleConfigUuid]: {...} }. */
export function setModuleRead(byUuid) {
  state = { modules: byUuid, at: Date.now() };
  emit();
}

/**
 * Forget what we believe is on the device.
 * `reason` is for debugging only -- callers pass "flash", "disconnected", etc.
 */
export function invalidateDeviceState(reason = "") {
  if (state.modules === null) return;
  state = { modules: null, at: 0, invalidatedBy: reason };
  emit();
}
