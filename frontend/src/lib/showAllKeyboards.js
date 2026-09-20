// Whether to keep showing keyboards that are no longer connected.
//
// Normally OFF. A keyboard that has been unplugged or powered off lingers in the backend's live
// map as a disconnected entry, which is exactly right when it is the ONLY keyboard -- "your
// right half is not answering" is the thing you need to be told. With a second keyboard still
// attached it is just a ghost pair cluttering the bar, and it kept the "Acting on" picker up
// after there was nothing left to choose between.
//
// So by default the app presents what is actually connected, and having two keyboards at once
// stops being visible the moment it stops being true. The toggle forces every keyboard to stay
// on screen, which is a troubleshooting aid for working on the multi-keyboard handling itself
// rather than something a user has a reason to turn on.
//
// Local to this machine, like the theme: it is about the screen in front of you, not the
// keyboard, so it does not belong in the backend's settings.
import { useSyncExternalStore } from "react";

const KEY = "openflow.showAllKeyboards";
const listeners = new Set();

function read() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

let on = read();

export function getShowAllKeyboards() {
  return on;
}

export function setShowAllKeyboards(next) {
  on = !!next;
  try {
    if (on) localStorage.setItem(KEY, "1");
    else localStorage.removeItem(KEY);
  } catch {}
  for (const l of listeners) l();
}

export function subscribeShowAllKeyboards(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useShowAllKeyboards() {
  return useSyncExternalStore(subscribeShowAllKeyboards, getShowAllKeyboards, () => false);
}

// The halves worth drawing right now.
//
// Drops keyboards with nothing connected, but ONLY while some other keyboard is connected:
// when the last one goes, its halves stay on screen saying they are disconnected, because that
// is the state a user most needs to see. Returns the list unchanged when the toggle is on, or
// when there is nothing to filter.
export function visibleHalves(halves, showAll = false) {
  const list = halves || [];
  if (showAll || list.length <= 2) return list;

  const live = new Set();
  for (const h of list) if (h.connected) live.add(h.keyboardId ?? 0);
  if (!live.size) return list;        // nothing is connected at all: show what we last knew

  return list.filter((h) => live.has(h.keyboardId ?? 0));
}
