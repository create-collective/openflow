// The backend's stream, as one connection for the whole app, carrying two named events.
//
// useSSE opened an EventSource per caller: the sidebar and the Hub each had their own, and the
// persistent profile bar would have made a third, all carrying the same six-second snapshot.
// One EventSource, opened by the first subscriber and kept for the app's lifetime (the sidebar
// is always mounted), with the same reconnect rule as before. Returns { data, connected }.
//
// sse:flash-progress is a firmware run's steps as they happen (SCRUM-102). It arrives on this
// same connection, which is why it lives here: opening a second EventSource for it would double
// the backend's tick and could still miss events the first one swallowed. The server sends only
// the events after the last sequence number it sent US, so they are accumulated here rather than
// replaced -- and a reconnect replays the run from the start, which is exactly what a page that
// was reloaded mid-flash needs.
import { useSyncExternalStore } from "react";
import { BASE } from "./api";

const EVENT = "sse:naya-devices-stream";
const FLASH_EVENT = "sse:flash-progress";
const MAX_RETRIES = 20;

let snapshot = { data: null, connected: false };
let flash = { run: null, events: [] };
let source = null;
let retries = 0;
const listeners = new Set();
const flashListeners = new Set();

function emit() {
  for (const l of listeners) l();
}

function emitFlash() {
  for (const l of flashListeners) l();
}

// One run's state, with the events appended rather than overwritten. A payload for a different
// run id starts a fresh list: the previous run is finished and its verdict is already on screen,
// and mixing two runs' steps into one list would be worse than showing none.
export function mergeFlash(prev, state) {
  if (!state || !state.id) return prev;
  const fresh = prev.run?.id !== state.id;
  const before = fresh ? [] : prev.events;
  const seen = before.length ? before[before.length - 1].seq : 0;
  const added = (state.events || []).filter((e) => e.seq > seen);
  return { run: state, events: added.length ? [...before, ...added] : before };
}

function connect() {
  const es = new EventSource(`${BASE}/sse`);
  source = es;
  es.onopen = () => {
    retries = 0;
    snapshot = { ...snapshot, connected: true };
    emit();
  };
  es.onerror = () => {
    snapshot = { ...snapshot, connected: false };
    emit();
    es.close();
    source = null;
    if (retries < MAX_RETRIES) {
      retries += 1;
      setTimeout(() => { if (!source) connect(); }, 3000);
    }
  };
  es.addEventListener(EVENT, (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { data = e.data; }
    snapshot = { ...snapshot, data };
    emit();
  });
  es.addEventListener(FLASH_EVENT, (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }
    flash = mergeFlash(flash, data);
    emitFlash();
  });
}

export function subscribeDeviceStream(listener) {
  listeners.add(listener);
  if (!source && typeof EventSource !== "undefined") connect();
  return () => listeners.delete(listener);
}

export function getDeviceStream() {
  return snapshot;
}

export function useDeviceStream() {
  return useSyncExternalStore(subscribeDeviceStream, getDeviceStream, getDeviceStream);
}

// --- the firmware run ------------------------------------------------------------------------ //

export function subscribeFlashProgress(listener) {
  flashListeners.add(listener);
  if (!source && typeof EventSource !== "undefined") connect();
  return () => flashListeners.delete(listener);
}

export function getFlashProgress() {
  return flash;
}

/** { run, events } for the run going now, or the last one this session saw. */
export function useFlashProgress() {
  return useSyncExternalStore(subscribeFlashProgress, getFlashProgress, getFlashProgress);
}

// The catch-up path: /api/flash-runs/current, for a window that opens while the stream is down
// or that started a run through a POST whose reply arrives before the first tick does.
export function seedFlashProgress(state) {
  flash = mergeFlash(flash, state);
  emitFlash();
}

export function resetFlashProgressForTests() {
  flash = { run: null, events: [] };
  emitFlash();
}
