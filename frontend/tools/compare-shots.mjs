// Pixel-compare two sets of route-walk screenshots.
//
// The theme-token commit claims the dark render is unchanged; this is what makes that claim
// checkable. Each PNG in <after> is compared with the same-named PNG in <before> using
// pixelmatch at its default threshold (0.1: shades one or two tonal stops apart count as
// equal, a moved or recoloured element does not). A diff image is written beside the report
// for every pair with differences.
//
//     node tools/compare-shots.mjs tests/e2e/shots/baseline-pre-port/dark tests/e2e/shots/dark
//     node tools/compare-shots.mjs <before> <after> --max 0        (exit 1 above the limit)
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

const args = process.argv.slice(2);
const [beforeDir, afterDir] = args.filter((a) => !a.startsWith("--")).map((p) => resolve(p));
const maxIdx = args.indexOf("--max");
const max = maxIdx >= 0 ? Number(args[maxIdx + 1]) : Infinity;
if (!beforeDir || !afterDir || !existsSync(beforeDir) || !existsSync(afterDir)) {
  console.error("usage: node tools/compare-shots.mjs <before-dir> <after-dir> [--max N]");
  process.exit(2);
}
const outDir = join(afterDir, "..", "diff-" + basename(afterDir));
mkdirSync(outDir, { recursive: true });

let worst = 0;
const rows = [];
for (const name of readdirSync(afterDir).filter((f) => f.endsWith(".png")).sort()) {
  const beforePath = join(beforeDir, name);
  if (!existsSync(beforePath)) { rows.push([name, "no baseline"]); continue; }
  const a = PNG.sync.read(readFileSync(beforePath));
  const b = PNG.sync.read(readFileSync(join(afterDir, name)));
  if (a.width !== b.width || a.height !== b.height) { rows.push([name, `size ${a.width}x${a.height} vs ${b.width}x${b.height}`]); worst = Infinity; continue; }
  const diff = new PNG({ width: a.width, height: a.height });
  const n = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: 0.1 });
  const pct = (100 * n) / (a.width * a.height);
  rows.push([name, `${n} px (${pct.toFixed(3)}%)`]);
  if (n > 0) writeFileSync(join(outDir, name), PNG.sync.write(diff));
  worst = Math.max(worst, n);
}
for (const [name, res] of rows) console.log(`${name.padEnd(24)} ${res}`);
console.log(`\nworst: ${worst} differing pixels${worst > 0 ? `; diffs in ${outDir}` : ""}`);
if (worst > max) process.exit(1);
