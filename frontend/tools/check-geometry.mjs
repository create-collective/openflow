#!/usr/bin/env node
// The board draws from a copy of the vendor-exact key geometry, docs/reference/create-key-geometry.json
// (exported from NayaFlow 1.25.1's own renderer by tools/export_key_geometry.js). The copy lives
// inside the frontend because Vite's dev server refuses imports from outside its root. The
// reference is the source of truth; this script keeps the copy honest.
//
//   node tools/check-geometry.mjs          exit 1 if the copy differs from the reference
//   node tools/check-geometry.mjs --sync   refresh the copy from the reference
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(here, "..", "..", "..", "docs", "reference", "create-key-geometry.json");
const COPY = path.resolve(here, "..", "src", "lib", "keygeometry.json");

const ref = fs.readFileSync(REFERENCE, "utf8");
if (process.argv.includes("--sync")) {
  fs.writeFileSync(COPY, ref);
  console.log(`synced ${path.relative(process.cwd(), COPY)} from ${path.relative(process.cwd(), REFERENCE)}`);
  process.exit(0);
}
let copy = null;
try { copy = fs.readFileSync(COPY, "utf8"); } catch { /* missing */ }
if (copy !== ref) {
  console.error(`${path.relative(process.cwd(), COPY)} differs from the reference ${path.relative(process.cwd(), REFERENCE)}; run: node tools/check-geometry.mjs --sync`);
  process.exit(1);
}
const g = JSON.parse(copy);
console.log(`key geometry copy is current (${g.counts.keys} keys, ${g.counts.leds} LEDs, ${g.counts.shapes} shapes, generated ${g.generated})`);
