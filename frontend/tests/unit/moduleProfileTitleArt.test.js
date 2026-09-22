// The picture beside a module PROFILE's name must be a file that exists.
//
// The Modules page's title bar built its own image path -- `/modules/v2/${type}.png` -- while
// the profile list next to it used a rule that knew better: there is no touch.png, only
// touch-left.png and touch-right.png, because the Touch's artwork is per hand while a profile
// has no hand. So "Naya Touch Windows" showed a broken image in its title and a good one in
// the list, from the same data. One exported rule now, and this test opens every file it can
// name -- the check that would have caught it.
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { moduleImg } from "../../src/components/ModuleProfileList";

const PUBLIC = join(__dirname, "..", "..", "public");

describe("a module profile's picture", () => {
  it("is the right-hand Touch for a Touch profile, whatever side is asked for", () => {
    expect(moduleImg("touch", "left")).toBe("/modules/v2/touch-right.png");
    expect(moduleImg("touch", "right")).toBe("/modules/v2/touch-right.png");
    expect(moduleImg("touch", undefined)).toBe("/modules/v2/touch-right.png");
  });

  it("follows the variant for a Track, which really is two different units", () => {
    expect(moduleImg("track", "left")).toBe("/modules/v2/track-left.png");
    expect(moduleImg("track", "right")).toBe("/modules/v2/track-right.png");
  });

  it("is the one Tune for a Tune", () => {
    expect(moduleImg("tune", "left")).toBe("/modules/v2/tune.png");
  });

  it("names only files that exist, for every type and side the rule can be given", () => {
    for (const type of ["touch", "track", "tune"]) {
      for (const side of ["left", "right", undefined]) {
        const url = moduleImg(type, side);
        expect(existsSync(join(PUBLIC, url)), `${type}/${side} -> ${url}`).toBe(true);
      }
    }
  });
});
