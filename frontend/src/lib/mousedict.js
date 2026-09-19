// What a virtual mouse can offer, and where each part sits on the drawing.
//
// Split from the component the way keydict.js is split from VirtualKeyboard: the layout is data,
// so it can be corrected without touching render code, and the codes can be checked against the
// encoder without a browser.
//
// Every code here is one the device actually takes on a module gesture, which is not the same as
// "every mouse thing ZMK can do":
//
//   * BUTTONS are a two-word record, category 3, selector = a bitmask. M1..M4 came off a
//     2026-09-02 Track capture; M5 = 16 was the obvious bit continuation and was proved on
//     hardware 2026-09-06 (browser Forward from a Tune tap).
//   * MOTION is the same record shape with a motion category and a signed selector, and it binds
//     to an AXIS, not to a tap -- an axis is two fields and the sign is the direction. So those
//     entries are `value` type and carry BOTH directions in one code.
//
// Deliberately absent: mouse on a KEY position. A key takes record type 0x00 with the same
// two-u32 body, but the category namespace is different there -- category 3 is BLUETOOTH on a
// key while it is mouse buttons on a module -- so the module numbers cannot be reused, and we
// have no capture of what a key uses. Offering it would be offering a binding that silently
// never reaches the board.

export const MOUSE_BUTTONS = [
  { code: "M1", label: "Left", hint: "Left click", area: "left" },
  { code: "M2", label: "Right", hint: "Right click", area: "right" },
  { code: "M3", label: "Middle", hint: "Middle click (the wheel)", area: "middle" },
  { code: "M4", label: "Back", hint: "Mouse 4 — browser Back", area: "side-back" },
  { code: "M5", label: "Forward", hint: "Mouse 5 — browser Forward", area: "side-fwd" },
];

// Direction PAIRS. A single code names both ends because that is how the device stores an axis:
// two fields whose selector sign is the direction. Splitting one is a per-half override, which
// the gesture row's own split control does.
export const MOUSE_MOTION = [
  {
    code: "mouse - SCROLL_UP - SCROLL_DOWN",
    label: "Vertical scroll",
    hint: "Wheel up and down. Binds to a vertical axis.",
    axis: "vertical",
  },
  {
    code: "mouse - SCROLL_LEFT - SCROLL_RIGHT",
    label: "Horizontal scroll",
    hint: "Wheel left and right. Binds to a horizontal axis.",
    axis: "horizontal",
  },
  {
    code: "mouse - MOUSE_DOWN - MOUSE_UP",
    label: "Vertical cursor",
    hint: "Move the pointer up and down. Binds to a vertical axis.",
    axis: "vertical",
  },
  {
    code: "mouse - MOUSE_LEFT - MOUSE_RIGHT",
    label: "Horizontal cursor",
    hint: "Move the pointer left and right. Binds to a horizontal axis.",
    axis: "horizontal",
  },
  {
    code: "mouse - ZOOM_OUT - ZOOM_IN",
    label: "Zoom",
    hint: "Zoom out and in. Binds to the 2-finger pinch axis on a Touch or Tune.",
    axis: "pinch & spread",
  },
];

// Single DIRECTIONS, for one half of a split axis. Each is the two-word motion record the
// stock pair writes for that half, with the direction's own category -- so a half can hold
// "scroll left" on its own, or a horizontal swipe can be made to scroll vertically.
export const MOUSE_DIRECTIONS = [
  { code: "SCROLL_UP", label: "Scroll up", hint: "Wheel up, one direction." },
  { code: "SCROLL_DOWN", label: "Scroll down", hint: "Wheel down, one direction." },
  { code: "SCROLL_LEFT", label: "Scroll left", hint: "Wheel left, one direction." },
  { code: "SCROLL_RIGHT", label: "Scroll right", hint: "Wheel right, one direction." },
  { code: "MOUSE_UP", label: "Cursor up", hint: "Move the pointer up, one direction." },
  { code: "MOUSE_DOWN", label: "Cursor down", hint: "Move the pointer down, one direction." },
  { code: "MOUSE_LEFT", label: "Cursor left", hint: "Move the pointer left, one direction." },
  { code: "MOUSE_RIGHT", label: "Cursor right", hint: "Move the pointer right, one direction." },
  { code: "ZOOM_OUT", label: "Zoom out", hint: "Zoom out, one direction." },
  { code: "ZOOM_IN", label: "Zoom in", hint: "Zoom in, one direction." },
];

/** What a pick sends. Buttons are a single action; motion is a direction pair. */
export function mousePick(code) {
  return { actionCode: code, actionType: code.includes(" - ") ? "value" : "mouse" };
}
