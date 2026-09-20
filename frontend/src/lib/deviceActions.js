// The whole-keyboard actions the persistent profile bar offers on every page: read the
// keyboard, and back the data up.
//
// They lived in Bindings.jsx, which is why only that page could read the keyboard. Now there is
// one bar and many pages, so this is a module-level store (the shape of deviceState.js) rather
// than a hook with its own state: the bar starts a read, the store does what every read means
// for the whole app (the profile list reloads, the profile the read produced becomes the active
// one, the module configs the board carries go into the shared device state, the session is
// marked as read), and a page with a follow-up of its own subscribes with useOnDeviceRead
// (Bindings repaints its bays and reloads its catalog; Modules reloads its list when the read
// captured a profile the board was running).
import { useEffect, useRef, useSyncExternalStore } from "react";
import { api } from "./api";
import { setActiveProfileId } from "./activeProfile";
import { setModuleRead } from "./deviceState";
import { reloadProfiles } from "./profilesStore";

// Has the keyboard been read in this app session? Flashing is gated on it: until the board has
// been read, the app's idea of the keymap may not match what is on the keyboard, and edits
// would be flashed over an unknown state. sessionStorage, so it lasts the window, not the machine.
const READ_KEY = "openflow.deviceRead";
export function hasReadDevice() {
  try {
    return Boolean(sessionStorage.getItem(READ_KEY));
  } catch {
    return false;
  }
}

const DONE_MS = 5000;
const EMPTY = { busy: null, err: null, readNote: null, saved: null, justRead: false };

let state = EMPTY;
let doneTimer = null;
const listeners = new Set();
const readListeners = new Set();

function emit() {
  for (const l of listeners) l();
}

function set(patch) {
  state = { ...state, ...patch };
  emit();
}

// The green "it worked" state on the Read button, for a few seconds: a read used to finish in
// total silence, and a success badge that stays forever stops meaning "just now".
function markRead() {
  clearTimeout(doneTimer);
  set({ justRead: true });
  doneTimer = setTimeout(() => set({ justRead: false }), DONE_MS);
}

/** Read the map on the connected keyboard into a profile and make that profile the active one.
 *
 * `target` is a half's serial, naming WHICH keyboard when more than one is attached. Passed in
 * by the caller, which already has the half list, rather than reached for from here. Omit it
 * with one keyboard: the backend then has nothing to disambiguate, and with several it refuses
 * rather than guessing (SCRUM-86). */
export async function readKeyboard(target = null) {
  if (state.busy) return null;
  set({ busy: "read", err: null, readNote: null });
  try {
    const r = await api.readKeyboard(target ? { target } : {});
    // The read may have produced a new profile: the list first, then the switch, so the
    // profile a page is asked to show is one it can find.
    await reloadProfiles();
    if (r.profileId) setActiveProfileId(r.profileId);
    // A read is a read wherever it was started from: publish the module configs the board
    // carries into the shared device state, so the Modules page shows the on-device marks
    // without having to read again.
    if (r.modules) {
      const byUuid = {};
      for (const m of r.modules) byUuid[m.uuid] = m;
      setModuleRead(byUuid);
    }
    try { sessionStorage.setItem(READ_KEY, String(Date.now())); } catch { /* ignore */ }
    for (const l of [...readListeners]) {
      // A page's follow-up failing does not undo a read that worked.
      try { await l(r); } catch { /* the page reports its own errors */ }
    }
    markRead();
    const captured = (r.captured || []).length;
    set({
      readNote: {
        at: new Date(),
        text: `${r.bindings} binding(s) across ${r.layers} layer(s)`
          + (captured ? ` · captured ${captured} module profile(s) the board was running` : ""),
        warnings: r.warnings?.length || 0,
      },
    });
    return r;
  } catch (e) {
    const noDev = /device|found|503|connect/i.test(e.message);
    set({ err: noDev ? "No keyboard found. Connect the Create over USB and close NayaFlow." : e.message });
    return null;
  } finally {
    set({ busy: null });
  }
}

/** Snapshot the data to a backup file. Edits are saved as they are made; this is a restore point. */
export async function backupNow() {
  if (state.busy) return;
  set({ busy: "save", err: null });
  try {
    await api.createBackup();
    set({ saved: new Date() });
  } catch (e) {
    set({ err: e.message });
  } finally {
    set({ busy: null });
  }
}

/** An edit means the map is no longer "backed up" until Back up is pressed again. */
export function clearSaved() {
  if (state.saved) set({ saved: null });
}

export function clearDeviceError() {
  if (state.err) set({ err: null });
}

export function subscribeDeviceActions(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getDeviceActions() {
  return state;
}

/** { busy, err, readNote, saved, justRead }, live. The actions themselves are plain exports. */
export function useDeviceActions() {
  return useSyncExternalStore(subscribeDeviceActions, getDeviceActions, getDeviceActions);
}

/** Be told after every successful read, with the backend's result. Returns the unsubscribe. */
export function onDeviceRead(listener) {
  readListeners.add(listener);
  return () => readListeners.delete(listener);
}

/** onDeviceRead for a component: the latest `fn` runs, however often the component re-renders. */
export function useOnDeviceRead(fn) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => onDeviceRead((r) => ref.current(r)), []);
}

/** Tests only. */
export function _resetDeviceActionsForTests() {
  clearTimeout(doneTimer);
  state = EMPTY;
  readListeners.clear();
}
