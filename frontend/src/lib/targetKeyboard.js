// Which keyboard a read or a flash acts on, when more than one is attached.
//
// With two Creates connected there are two legitimate left halves, and the backend refuses to
// guess between them rather than silently picking one: a flash goes to the left half, so
// choosing for the user is how it lands on the wrong keyboard (SCRUM-86). This is where the
// user's choice lives, and it is sent as `target` on read and flash.
//
// The value is a HALF'S SERIAL, not the keyboardId, because the id is just a position in the
// last reading and would come to mean a different board the moment something is replugged.
//
// Deliberately NOT persisted. It describes what is plugged in right now, and a remembered
// serial from a previous session would be a stale answer to "which keyboard", which is exactly
// the ambiguity this exists to remove. The normal case is one keyboard and no choice at all.
import { useSyncExternalStore } from "react";

const listeners = new Set();
let serial = null;

function emit() {
  for (const l of listeners) l();
}

export function getTargetKeyboard() {
  return serial;
}

export function setTargetKeyboard(next) {
  serial = next || null;
  emit();
}

export function subscribeTargetKeyboard(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTargetKeyboard() {
  return useSyncExternalStore(subscribeTargetKeyboard, getTargetKeyboard, () => null);
}

// The half whose serial a command should carry, for the keyboard the user picked.
//
// Commands go to a SIDE, and the serial names one half, so the target has to be the half of
// that side belonging to the chosen keyboard. Returns null when there is nothing to
// disambiguate, which keeps the single-keyboard case sending no target at all.
export function targetSerialFor(halves, side = "left") {
  const list = halves || [];
  if (list.length <= 2) return null;
  const chosen = list.find((h) => h.serialNumber && h.serialNumber === serial);
  if (!chosen) return null;
  const mate = list.find((h) => h.keyboardId === chosen.keyboardId && h.side === side);
  return (mate || chosen).serialNumber || null;
}

// Keyboards to offer, newest reading first. One entry per keyboardId, labelled by its left
// half's serial where there is one, because that is the half a flash actually writes to.
export function keyboardChoices(halves) {
  const out = [];
  for (const h of halves || []) {
    const id = h.keyboardId ?? 0;
    let found = out.find((b) => b.id === id);
    if (!found) { found = { id, halves: [] }; out.push(found); }
    found.halves.push(h);
  }
  return out.map((b, n) => {
    const left = b.halves.find((h) => h.side === "left") || b.halves[0];
    return { id: b.id, label: `Keyboard ${n + 1}`, serial: left?.serialNumber || null,
             firmware: left?.firmwareVersion || null };
  });
}
