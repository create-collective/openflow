// The multi-behaviour star must be drawn INSIDE the cap it belongs to (SCRUM-111).
//
// It used to be pinned to the cap button's bottom-left corner. The button is the SVG's box, but
// the drawn silhouette does not fill it: the inner-column caps (gtt beside the right module bay,
// btt, ktt, Ett) have their bottom-left cut away, so the star floated in the empty margin -- on
// the neighbouring key, or on the bay next to Backspace. On the right half the box's left edge
// faces the centre of the board, which is why it looked like "the right side's positions are
// wrong". They were not; the data was on the right cap, the glyph was not.
//
// This test is geometry, not rendering: it parses every path in SHAPES into a polygon and checks
// the badge anchor against it with a point-in-polygon test, the same measurement that chose the
// offset. A shape added later that breaks the invariant fails here rather than in a screenshot.
import { describe, expect, it } from "vitest";
import { BADGE_DX, BADGE_DY, SHAPES, badgeAnchor } from "../../src/lib/keyshapes";

// Vertices of an SVG path (absolute coordinates; curves contribute their end points, which is
// enough for these caps -- their curves are corner rounding, never the whole edge).
function vertices(d) {
  const out = [];
  const toks = d.match(/[MLHVCSQTAZmlhvcsqtaz]|-?\d*\.?\d+(?:e-?\d+)?/g) || [];
  let x = 0, y = 0, cmd = "", i = 0;
  const n = () => parseFloat(toks[i++]);
  while (i < toks.length) {
    const t = toks[i];
    if (/[A-Za-z]/.test(t)) { cmd = t; i++; continue; }
    switch (cmd) {
      case "M": case "L": case "T": x = n(); y = n(); out.push([x, y]); break;
      case "m": case "l": case "t": x += n(); y += n(); out.push([x, y]); break;
      case "H": x = n(); out.push([x, y]); break;
      case "h": x += n(); out.push([x, y]); break;
      case "V": y = n(); out.push([x, y]); break;
      case "v": y += n(); out.push([x, y]); break;
      case "C": n(); n(); n(); n(); x = n(); y = n(); out.push([x, y]); break;
      case "c": n(); n(); n(); n(); x += n(); y += n(); out.push([x, y]); break;
      case "S": case "Q": n(); n(); x = n(); y = n(); out.push([x, y]); break;
      case "s": case "q": n(); n(); x += n(); y += n(); out.push([x, y]); break;
      case "A": n(); n(); n(); n(); n(); x = n(); y = n(); out.push([x, y]); break;
      case "a": n(); n(); n(); n(); n(); x += n(); y += n(); out.push([x, y]); break;
      default: i++;
    }
  }
  return out;
}

function inside([px, py], poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) c = !c;
  }
  return c;
}

const pct = (s) => parseFloat(String(s));
const box = (shape) => shape.viewBox.split(" ").slice(2).map(Number);

// The point badgeAnchor() resolves to, in viewBox units, without a browser to evaluate calc().
function anchorPoint(shape) {
  const [w, h] = box(shape);
  return [w * (pct(shape.legend.left) + BADGE_DX) / 100, h * (pct(shape.legend.top) + BADGE_DY) / 100];
}

const pathShapes = Object.entries(SHAPES).filter(([, s]) => s.d);

describe("the multi-behaviour star sits inside its cap", () => {
  it("covers every path shape, not a hand-picked few", () => {
    expect(pathShapes.length).toBeGreaterThanOrEqual(30);
  });

  it.each(pathShapes)("%s", (_name, shape) => {
    expect(inside(anchorPoint(shape), vertices(shape.d))).toBe(true);
  });

  it("has margin: the anchor stays inside if nudged 8% in any direction", () => {
    // A choice that only just clears an edge would fail on the first font or DPI change.
    for (const [name, shape] of pathShapes) {
      const [w, h] = box(shape);
      const [ax, ay] = anchorPoint(shape);
      const poly = vertices(shape.d);
      for (const [dx, dy] of [[-8, 0], [8, 0], [0, -8], [0, 8]]) {
        expect(inside([ax + w * dx / 100, ay + h * dy / 100], poly), `${name} nudged ${dx},${dy}`).toBe(true);
      }
    }
  });

  it("would have failed for the old corner pin, which is why this exists", () => {
    // bottom: 2px; left: 3px on a 45x100 box is (3, 98): outside the tall inner caps.
    const gtt = SHAPES.gtt;                       // Backspace's cap, beside the right module bay
    const [, h] = box(gtt);
    expect(inside([3, h - 2], vertices(gtt.d))).toBe(false);
  });

  it("badgeAnchor produces calc() offsets from the legend point", () => {
    expect(badgeAnchor({ legend: { top: "45%", left: "50%" } }))
      .toEqual({ top: "calc(45% + 20%)", left: "calc(50% + -20%)" });
    expect(badgeAnchor(undefined).top).toBe("calc(50% + 20%)");
  });
});
