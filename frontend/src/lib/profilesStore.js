// The keyboard profiles (with their layers and keys), fetched once and shared.
//
// Bindings and LED Map each kept their own copy and refetched it after every edit; a persistent
// profile bar would have been a third. One store: any mutation calls reloadProfiles(), one
// request goes out, and every subscriber sees the same list. `version` ticks on each reload so
// a page can run its own follow-up when the profiles change.
import { useEffect, useSyncExternalStore } from "react";
import { api } from "./api";

let state = { profiles: [], loaded: false, error: null, version: 0 };
let inflight = null;
const listeners = new Set();

function emit() {
  for (const l of listeners) l();
}

export function getProfiles() {
  return state;
}

export function subscribeProfiles(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Fetch the profiles again and notify everyone. Concurrent calls share one request. */
export function reloadProfiles() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const ud = await api.userdata();
      state = { profiles: ud.profiles || [], loaded: true, error: null, version: state.version + 1 };
    } catch (e) {
      state = { ...state, loaded: true, error: e.message, version: state.version + 1 };
    } finally {
      inflight = null;
    }
    emit();
    return state.profiles;
  })();
  return inflight;
}

/** The profiles, live; the first subscriber triggers the initial load. */
export function useProfiles() {
  const s = useSyncExternalStore(subscribeProfiles, getProfiles, getProfiles);
  useEffect(() => {
    if (!s.loaded && !inflight) reloadProfiles();
  }, [s.loaded]);
  return s;
}

/** Tests only: back to an empty, unloaded store. */
export function _resetProfilesForTests() {
  state = { profiles: [], loaded: false, error: null, version: 0 };
  inflight = null;
}
