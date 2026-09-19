// What the board draws in each bay, and when it is allowed to change its mind.
//
// The bug: unplugging BOTH modules left the last one on screen. The board only repainted when
// at least one bay was filled, so pulling one of two repainted fine and pulling the second was
// ignored. Not specific to either module -- it is whichever comes out last. The profile bar was
// right throughout, because it renders the halves directly with no such guard.
//
// The guard was protecting something real: do not blank the bays when there is no information.
// It just could not tell that apart from "we asked, and nothing is docked".
import { describe, expect, it } from "vitest";
import { baysFromHalves } from "../../src/lib/dockedModules";

// pages/Bindings.jsx
const paintBays = (b, previous) => (b ? b : previous);

const BOTH = [
  { side: "left", module: { type: "Tune", docked: "left" } },
  { side: "right", module: { type: "Touch", docked: "right" } },
];
const PAINTED = { left: "tune", right: "touch" };

describe("baysFromHalves tells 'nothing docked' apart from 'we were told nothing'", () => {
  it("maps each docked module to its bay", () => {
    expect(baysFromHalves(BOTH)).toEqual(PAINTED);
  });

  it("reports empty bays when the halves are connected but carry no modules", () => {
    // The case that was being thrown away.
    expect(baysFromHalves([{ side: "left", module: null }, { side: "right", module: null }]))
      .toEqual({ left: null, right: null });
  });

  it("returns null when there are no halves at all", () => {
    expect(baysFromHalves(undefined)).toBe(null);
    expect(baysFromHalves(null)).toBe(null);
  });

  it("treats an empty list as an answer: no keyboard means nothing docked", () => {
    expect(baysFromHalves([])).toEqual({ left: null, right: null });
  });

  it("follows the dock address over the port that answered", () => {
    // A module reports which half it is docked on; that is measured, the port is not.
    expect(baysFromHalves([{ side: "right", module: { type: "Tune", docked: "left" } }]))
      .toEqual({ left: "tune", right: null });
  });

  it("leaves a bay empty for a module type with no artwork", () => {
    expect(baysFromHalves([{ side: "left", module: { type: "Float", docked: "left" } }]))
      .toEqual({ left: null, right: null });
  });
});

describe("the board repaints only when it was told something", () => {
  it("clears the last module when both are unplugged", () => {
    const told = baysFromHalves([{ side: "left", module: null }, { side: "right", module: null }]);
    expect(paintBays(told, PAINTED)).toEqual({ left: null, right: null });
  });

  it("clears one bay when one module is unplugged", () => {
    const told = baysFromHalves([BOTH[0], { side: "right", module: null }]);
    expect(paintBays(told, PAINTED)).toEqual({ left: "tune", right: null });
  });

  it("keeps the picture when nothing has been read yet", () => {
    expect(paintBays(baysFromHalves(undefined), PAINTED)).toEqual(PAINTED);
  });
});
