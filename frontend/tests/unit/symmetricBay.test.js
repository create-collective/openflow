// A symmetric bay control (Touch, Tune) governs BOTH bays, so it has to read both (SCRUM-92).
//
// Writing already did: set_layer_bay with no side sets left and right. Reading defaulted a
// missing side to "left", so a Touch assigned only to the RIGHT bay displayed as "Disabled"
// while the board really was running a profile there. Our own boards never show it, because
// every write we make sets both sides -- which is exactly why it survived so long.
//
// The resolution logic lives inside a useMemo in Bindings.jsx, so it is reproduced here rather
// than imported. That is a real limitation of this test: it pins the RULE, not the call site.
// The rule is small and stated once, and the alternative is rendering the whole page to assert
// one lookup.
import { describe, expect, it } from "vitest";

const TYPE_OF = { to: "TOUCH", to2: "TOUCH", tu: "TUNE", tl: "TRACK" };

// --- the rule, as Bindings.jsx applies it ------------------------------------------------------
const key = (type, side) => `${type}:keyboard_${side}`;
const sidesOf = (side) => (side ? [side] : ["left", "right"]);

const oneBay = (layer, type, side) => {
  const v = layer?.bays?.[key(type, side)];
  if (!v || v === "transparent") return null;
  if (v === "disabled") return v;
  return TYPE_OF[v] === type.toUpperCase() ? v : null;
};
const ownFor = (layer, type, side) => {
  const vals = sidesOf(side).map((s) => oneBay(layer, type, s));
  return vals.find((v) => v && v !== "disabled") ?? vals.find((v) => v) ?? null;
};
const splitFor = (layer, type, side) => {
  if (side) return false;
  return oneBay(layer, type, "left") !== oneBay(layer, type, "right");
};

// The donor board that exposed this: touch disabled on the left, a profile on the right.
const DONOR = { bays: {
  "touch:keyboard_left": "disabled", "touch:keyboard_right": "to",
  "tune:keyboard_left": "tu", "tune:keyboard_right": "disabled",
} };

describe("a symmetric bay control reads both bays", () => {
  it("finds a Touch assigned only to the right bay", () => {
    // The reported bug: this answered "disabled".
    expect(ownFor(DONOR, "touch", null)).toBe("to");
  });

  it("still finds a Tune assigned only to the left bay", () => {
    // This one always worked, but only by luck -- it happened to be on the side we read.
    expect(ownFor(DONOR, "tune", null)).toBe("tu");
  });

  it("reports that the two bays disagree", () => {
    expect(splitFor(DONOR, "touch", null)).toBe(true);
    expect(splitFor(DONOR, "tune", null)).toBe(true);
  });

  it("prefers an assigned bay over a disabled one, whichever side it is on", () => {
    const rightOnly = { bays: { "touch:keyboard_left": "disabled", "touch:keyboard_right": "to" } };
    const leftOnly = { bays: { "touch:keyboard_left": "to", "touch:keyboard_right": "disabled" } };
    expect(ownFor(rightOnly, "touch", null)).toBe("to");
    expect(ownFor(leftOnly, "touch", null)).toBe("to");
  });

  it("says disabled only when BOTH bays are disabled", () => {
    const both = { bays: { "touch:keyboard_left": "disabled", "touch:keyboard_right": "disabled" } };
    expect(ownFor(both, "touch", null)).toBe("disabled");
    expect(splitFor(both, "touch", null)).toBe(false);
  });

  it("leaves an unset control unset", () => {
    expect(ownFor({ bays: {} }, "touch", null)).toBe(null);
    expect(splitFor({ bays: {} }, "touch", null)).toBe(false);
  });

  it("does not flag a split when the sides agree", () => {
    const agree = { bays: { "touch:keyboard_left": "to", "touch:keyboard_right": "to" } };
    expect(ownFor(agree, "touch", null)).toBe("to");
    expect(splitFor(agree, "touch", null)).toBe(false);
  });

  it("leaves an asymmetric control alone: a Track side reads only its own bay", () => {
    const track = { bays: { "track:keyboard_left": "tl", "track:keyboard_right": "disabled" } };
    expect(ownFor(track, "track", "left")).toBe("tl");
    expect(ownFor(track, "track", "right")).toBe("disabled");
    expect(splitFor(track, "track", "left")).toBe(false);
  });

  it("still rejects a value of the wrong type in a bay", () => {
    // A read once stored a Track id in a Tune bay; that bay counts as unset, not as a Track.
    const wrong = { bays: { "tune:keyboard_left": "tl", "tune:keyboard_right": "tu" } };
    expect(ownFor(wrong, "tune", null)).toBe("tu");
  });
});
