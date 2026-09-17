// Which keyboard profile the app is working on, shared by every page.
//
// It was a localStorage key that three places read and two wrote, with no way for a page to
// learn that another had switched: FlashButton could flash a profile the Bindings page had
// already left. One external store (the shape deviceState.js uses), still persisted under the
// same key so nothing already saved is lost.
import { useSyncExternalStore } from "react";

const KEY = "openflow.activeProfile";
const listeners = new Set();

function read() {
  try {
    return localStorage.getItem(KEY) || null;
  } catch {
    return null;
  }
}

let id = read();

function emit() {
  for (const l of listeners) l();
}

export function getActiveProfileId() {
  return id;
}

export function setActiveProfileId(next) {
  id = next || null;
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch {}
  emit();
}

export function subscribeActiveProfile(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useActiveProfileId() {
  return useSyncExternalStore(subscribeActiveProfile, getActiveProfileId, () => null);
}
