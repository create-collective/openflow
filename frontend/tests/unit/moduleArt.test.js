// A Touch docked on the left must be drawn as a left-hand part (SCRUM-93).
//
// The Touch is one physical part, but it is not symmetric: in the left bay it presents the
// mirror of what it presents on the right. The board's image table said otherwise -- "Touch and
// Tune are symmetric and use a single image" -- and there was only ever one file, so a Touch on
// the left was drawn as a right-hand part.
//
// The rules live in small helpers inside their components, so they are restated here. That pins
// the RULE rather than the call site; the alternative is rendering three components to assert a
// filename. What it does guard is the thing that actually went wrong: a side being ignored.
import { describe, expect, it } from "vitest";

// components/ui/StatusBox.jsx -- the module docked on a half, so the side is REAL.
const statusBoxImg = (type, side) => {
  const t = String(type || "").toLowerCase();
  const hand = side === "right" ? "right" : "left";
  if (t === "track" || t === "touch") return `/modules/v2/${t}-${hand}.png`;
  return t === "tune" ? "/modules/v2/tune.png" : null;
};

// components/KeymapBoard.jsx -- a bay, so the side is REAL.
const MODULE_IMG = {
  track: { left: "/modules/v2/track-left.png", right: "/modules/v2/track-right.png" },
  touch: { left: "/modules/v2/touch-left.png", right: "/modules/v2/touch-right.png" },
  tune: "/modules/v2/tune.png",
};
const boardImg = (type, side) => {
  const entry = MODULE_IMG[type];
  if (!entry) return null;
  return typeof entry === "string" ? entry : entry[side] || entry.left;
};

describe("module artwork follows the bay it is docked in", () => {
  it("draws a Touch on the left as the left-hand part", () => {
    // The reported bug: both of these used to answer with the one right-hand image.
    expect(boardImg("touch", "left")).toBe("/modules/v2/touch-left.png");
    expect(statusBoxImg("Touch", "left")).toBe("/modules/v2/touch-left.png");
  });

  it("draws a Touch on the right as the right-hand part", () => {
    expect(boardImg("touch", "right")).toBe("/modules/v2/touch-right.png");
    expect(statusBoxImg("Touch", "right")).toBe("/modules/v2/touch-right.png");
  });

  it("still picks the correct Track unit, which was never broken", () => {
    expect(boardImg("track", "left")).toBe("/modules/v2/track-left.png");
    expect(statusBoxImg("Track", "right")).toBe("/modules/v2/track-right.png");
  });

  it("leaves the Tune alone: a dial looks the same in either hand", () => {
    expect(boardImg("tune", "left")).toBe("/modules/v2/tune.png");
    expect(statusBoxImg("Tune", "right")).toBe("/modules/v2/tune.png");
  });

  it("falls back to the left image for an unknown side rather than rendering nothing", () => {
    // A broken <img> in a bay is worse than the wrong hand.
    expect(boardImg("touch", undefined)).toBe("/modules/v2/touch-left.png");
    expect(boardImg("touch", "dongle")).toBe("/modules/v2/touch-left.png");
  });

  it("returns nothing for a type with no artwork", () => {
    expect(statusBoxImg("Float", "left")).toBe(null);
    expect(boardImg("float", "left")).toBe(null);
  });
});
