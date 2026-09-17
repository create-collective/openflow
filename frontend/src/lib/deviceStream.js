// The backend's device stream (sse:naya-devices-stream), as one connection for the whole app.
//
// useSSE opened an EventSource per caller: the sidebar and the Hub each had their own, and the
// persistent profile bar would have made a third, all carrying the same six-second snapshot.
// One EventSource, opened by the first subscriber and kept for the app's lifetime (the sidebar
// is always mounted), with the same reconnect rule as before. Returns { data, connected }.
import { useSyncExternalStore } from "react";
import { BASE } from "./api";

const EVENT = "sse:naya-devices-stream";
const MAX_RETRIES = 20;

let snapshot = { data: null, connected: false };
let source = null;
let retries = 0;
const listeners = new Set();

function emit() {
  for (const l of listeners) l();
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
