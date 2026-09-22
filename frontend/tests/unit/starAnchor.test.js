// The multi-behaviour star sits at the bottom-left corner of the cap it belongs to -- of the
// DRAWN cap, not its box (SCRUM-111).
//
// It used to be pinned to the cap button's bottom-left corner. The button is the SVG's box, but
// the drawn silhouette does not fill it: the inner-column caps (gtt beside the right module bay,
// btt, ktt, Ett) have their bottom-left cut away, so the star floated in the empty margin -- on
// the neighbouring key, or on the bay next to Backspace. On the right half the box's left edge
// faces the centre of the board, which is why it looked like "the right side's positions are
// wrong". They were not; the data was on the right cap, the glyph was not.
//
// The owner wants the star where it always was, the cap's own bottom-left corner. On a cut-away
// cap that corner is simply further up the left edge. keyshapes.badgePoint computes it from the
// path; this test checks every shape with the same point-in-polygon measurement, so a shape added
// later that breaks the placement fails here rather than in a screenshot.
import { describe, expect, it } from "vitest";
import {
  BADGE_CLEARANCE, POS_SHAPE, SHAPES, badgeAnchor, badgePoint, pathVertices, pointInPolygon,
} from "../../src/lib/keyshapes";
import { LEFT_COLS, LEFT_THUMBS, RIGHT_COLS, RIGHT_THUMBS } from "../../src/lib/boardgeom";

const box = (shape) => shape.viewBox.split(" ").slice(2).map(Number);
// Only shapes a KeyCap draws can carry a star: the column keys and the thumbs, positions 0-73.
// The LED edge strips (pi) and the module bays (gi) are drawn by LedCol and ModuleSlot and never
// get one, so the corner rule is not asserted for them.
const capPositions = new Set([
  ...LEFT_COLS.flatMap((c) => c.keys), ...RIGHT_COLS.flatMap((c) => c.keys),
  ...LEFT_THUMBS, ...RIGHT_THUMBS,
]);
const capShapeNames = new Set(POS_SHAPE.filter((_, pos) => capPositions.has(pos)));
const capShapes = Object.entries(SHAPES).filter(([name]) => capShapeNames.has(name));
const pathShapes = capShapes.filter(([, s]) => s.d);
const rectShapes = capShapes.filter(([, s]) => s.rect);

describe("the multi-behaviour star sits at its cap's own bottom-left corner", () => {
  it("covers every shape, not a hand-picked few", () => {
    expect(pathShapes.length).toBeGreaterThanOrEqual(30);
    expect(rectShapes.length).toBeGreaterThanOrEqual(1);
  });

  it.each(pathShapes)("%s: inside the silhouette with half a glyph of clearance", (_name, shape) => {
    const poly = pathVertices(shape.d);
    const [x, y] = badgePoint(shape);
    for (const [dx, dy] of [[0, 0], [BADGE_CLEARANCE, 0], [-BADGE_CLEARANCE, 0], [0, BADGE_CLEARANCE], [0, -BADGE_CLEARANCE]]) {
      expect(pointInPolygon([x + dx, y + dy], poly), `offset ${dx},${dy}`).toBe(true);
    }
  });

  it.each(pathShapes)("%s: in the bottom-left region, not drifted toward the middle", (_name, shape) => {
    // What the owner asked for, pinned: the star belongs at the corner, wherever that corner is.
    const [vw, vh] = box(shape);
    const [x, y] = badgePoint(shape);
    expect(x / vw).toBeLessThanOrEqual(0.35);
    expect(y / vh).toBeGreaterThanOrEqual(0.55);
  });

  it.each(rectShapes)("%s: a rectangular cap keeps the plain corner", (_name, shape) => {
    const [x, y] = badgePoint(shape);
    const r = shape.rect;
    expect(x).toBeGreaterThan(r.x);
    expect(x).toBeLessThan(r.x + r.w / 3);
    expect(y).toBeLessThan(r.y + r.h);
    expect(y).toBeGreaterThan(r.y + (2 * r.h) / 3);
  });

  it("would have failed for the old box-corner pin, which is why this exists", () => {
    // bottom: 2px; left: 3px on a 45x100 box is (3, 98): outside Backspace's cap.
    const gtt = SHAPES.gtt;
    const [, h] = box(gtt);
    expect(pointInPolygon([3, h - 2], pathVertices(gtt.d))).toBe(false);
  });

  it("badgeAnchor gives percentages of the box, centred by the stylesheet's translate", () => {
    const a = badgeAnchor(SHAPES.gtt);
    expect(a.left).toMatch(/^\d+(\.\d+)?%$/);
    expect(a.top).toMatch(/^\d+(\.\d+)?%$/);
    expect(badgeAnchor(undefined)).toEqual({ top: "50%", left: "50%" });
  });
});
