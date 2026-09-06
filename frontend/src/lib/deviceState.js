// What we currently believe is ON the keyboard, shared across pages.
//
// A device read is expensive (it opens the COM port and walks every slot) and it is a
// whole-app fact, not one page's state. Keeping it in a component meant navigating to
// Bindings and back threw it away and the user had to read again to see which module
// profiles the board carries.
//
// It IS persisted now, server-side, and that is a deliberate reversal. The original reasoning
// -- that surviving a reload would mean claiming knowledge of a keyboard we have not talked to
// since -- was right about the risk and wrong about the remedy. Forgetting made the live tags
// and blue dots vanish on every refresh, which looked like a broken read twice in one session.
//
// The honest fix is not to forget but to say WHEN: the state carries the time it was taken,
// and anything showing it must say "as of HH:MM" rather than presenting it as current truth.
//
// Invalidated by: another read (replaces it), a flash (we just changed the device, and the
// flash knows what it SENT, not what the board now reports), and the connection dropping.

let state = { modules: null, at: 0 };
const listeners = new Set();
let hydrated = false;

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

/**
 * Seed from the server's record of the last read. Called once at startup.
 *
 * A read that has happened since wins: hydration is slower than a click, and overwriting a
 * fresh read with a stale one would be worse than not hydrating at all.
 */
export async function hydrateDeviceState(api) {
  if (hydrated) return;
  hydrated = true;
  try {
    const r = await api.deviceState();
    if (state.modules !== null) return;             // a live read beat us to it
    if (!r || !Array.isArray(r.modules) || !r.modules.length) return;
    const byUuid = {};
    for (const m of r.modules) if (m && m.uuid) byUuid[m.uuid] = m;
    state = { modules: byUuid, at: r.at ? Date.parse(r.at + "Z") || 0 : 0, from: "stored" };
    emit();
  } catch {
    /* no stored state, or the backend is down: the app works without it */
  }
}

/** When the current belief was formed, as a Date, or null if we have never read. */
export function deviceStateAt() {
  return state.at ? new Date(state.at) : null;
}

/** True when it came from storage rather than a read in this session. */
export function deviceStateIsStored() {
  return !!state.from;
}
