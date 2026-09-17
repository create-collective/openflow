// What the Modules page calls things: gesture names, action labels, badges, axis halves.
// Pure functions, so they are testable on their own and the page and its components share
// one vocabulary instead of each carrying a copy.
import { MOUSE_DIRECTIONS } from "./mousedict";
import { shortcutInfo, shortcutLabel } from "./shortcutNames";

export const TYPE_ORDER = ["TOUCH", "TRACK", "TUNE"];

// Canonical gesture order so Track Left / Right (and every config) list the same way: the DB
// returns them in inconsistent orders.
const GESTURE_ORDER = ["vertical", "horizontal", "rotate", "tap",
  "swipe_up", "swipe_down", "swipe_left", "swipe_right"];
export function gestureIndex(g) {
  const i = GESTURE_ORDER.indexOf(g);
  return i === -1 ? 99 : i;
}
export const byGesture = (a, b) => gestureIndex(a.gesture) - gestureIndex(b.gesture);

// Behaviors whose slug does not read as a name. Pinch and spread are ONE gesture on this
// hardware (a single "pinch + tap"), so it is one row, not two.
export const GESTURE_LABEL = { pinch: "Pinch & Spread" };
export function gestureName(gesture) {
  return GESTURE_LABEL[gesture] || (gesture || "").replace(/_/g, " ");
}

export function cleanCode(code) {
  if (!code) return "—";
  // A known shortcut is shown by what it DOES, with the keys after it. Anything else falls back
  // to the stored code, tidied only enough to read.
  if (shortcutInfo(code)) return shortcutLabel(code, { withChord: true });
  return code.replaceAll(" - ", " / ").replaceAll("_", " ");
}

// The name the catalog gives an action, falling back to the tidied code. Without this the
// palette button reads "Vertical Scroll" and the row it writes reads
// "mouse / SCROLL UP / SCROLL DOWN": the same value under two different names, and the uglier
// one is the one that sticks around after the click.
export function makeLabelFor(actions) {
  const byCode = new Map((actions || []).filter((a) => a.code).map((a) => [a.code, a.label]));
  // The eight single directions a split half can hold are not catalog actions (they are the
  // halves of the motion pairs), so their names come from the mouse dictionary.
  for (const d of MOUSE_DIRECTIONS) if (!byCode.has(d.code)) byCode.set(d.code, d.label);
  return (code) => (code && byCode.get(code)) || cleanCode(code);
}

// A RAW_ code is the decoder saying it could not name what the field holds. Two different
// things arrive here and they must not be flattened into one:
//
//   RAW_p00:00m00  a KEY_PRESS whose payload is all zeros: page 0, usage 0, no modifiers. It
//                  presses nothing, but it is NOT unbound: an unbound field has record type
//                  NONE and no payload at all. The board carries this on the Tune gestures
//                  NayaFlow labels LED Brightness, i.e. a gesture the keyboard handles itself
//                  and never reports to the host.
//   RAW_<hex>      bytes we genuinely cannot name yet.
//
// Neither is "Unassigned", and saying so would be inventing knowledge; the whole point of the
// RAW prefix is that we do not have it. Both render muted, like a placeholder rather than a
// value.
export function displayAction(code, labelFor) {
  if (!code) return { text: "Unassigned", muted: true };
  if (code === "RAW_p00:00m00") {
    return { text: "Keyboard action", muted: true,
             title: "The keyboard claims this gesture and handles it itself — it sends nothing to "
                  + "the computer. This is what the board stores for its own LED brightness "
                  + "gestures. It is not the same as unassigned." };
  }
  if (code.startsWith("RAW_")) {
    return { text: "Unrecognised", muted: true,
             title: `The field holds ${code.slice(4)}, which OpenFlow cannot name yet. It is left `
                  + "exactly as it is unless you bind something else here." };
  }
  return { text: labelFor(code), muted: false };
}

export function targetLabel(t) {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Action types each device field kind can actually hold (data-backed, mirrors the backend's
// module_fields.action_ok_for_kind). Only these are offered when a gesture maps to a real
// device field, so the UI cannot stage something the firmware refuses. A gesture field is not
// locked to one record type: the same field takes a keypress OR a mouse button, and the TYPE
// byte decides. Proven on hardware twice: Tune 0x08 took both, and NayaFlow wrote KEYPRESS
// records into the Track button fields that normally hold masks.
const CLICK_TYPES = new Set(["key", "modifier", "shortcut_alias", "mouse"]);
export function okForKind(actionType, fieldKind) {
  if (actionType === "none") return true;
  if (fieldKind === "keypress" || fieldKind === "mouse_button") return CLICK_TYPES.has(actionType);
  if (fieldKind === "axis") return actionType === "value";
  return true; // no device field (DB-only): do not restrict, but the row is badged
}

// One badge for the gesture rows AND the axis half rows. They were built separately once, so
// the halves carried no status badge at all: a field that IS flashable looked identical to one
// that is app-only.
export function statusBadge({ unsupported, flashable, locked }) {
  if (locked) {
    return { tone: "ok", text: "firmware",
             title: "The module's firmware does this itself while the field is empty, and the keyboard is flashed that way. NayaFlow locks it too." };
  }
  if (unsupported) {
    return { tone: "neutral", text: "experimental",
             title: "The Track has one field per button and no room for a hold. NayaFlow lets you set one and silently overwrites the tap; we do not." };
  }
  if (flashable) {
    return { tone: "ok", text: "flashable",
             title: "This gesture is stored on the device and can be flashed." };
  }
  return { tone: "neutral", text: "app only",
           title: "No device field for this gesture yet — edits stay in the app until confirmed." };
}

// An axis half is addressed by behavior + direction rather than by a binding id, so it needs a
// selection id of its own to be a palette target.
export const AXIS_HALF_LABEL = {
  vertical: ["Up", "Down"], horizontal: ["Left", "Right"],
  rotate: ["Rotate left", "Rotate right"],
};
export function axisHalfNames(behavior) {
  const head = (behavior || "").split(":")[0];
  return AXIS_HALF_LABEL[head] || ["–", "+"];
}
export const axisHalfId = (behavior, side) => `axis:${behavior}:${side}`;
export function parseAxisHalfId(id) {
  if (typeof id !== "string" || !id.startsWith("axis:")) return null;
  const side = id.slice(-1);
  return { behavior: id.slice(5, -2), side };
}
