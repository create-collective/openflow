// Renders public/brand/openflow-icon.svg to ../build/icon.png at 1024 px, the one raster the
// desktop build needs (electron-builder derives .ico and .icns from it). Uses the Playwright
// Chromium the route walk already installs, so the vector and the raster cannot drift.
//
//     node tools/render-icon.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const svg = readFileSync(join(here, "..", "public", "brand", "openflow-icon.svg"), "utf8");
const out = join(here, "..", "..", "build", "icon.png");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
await page.setContent(`<!doctype html><html><body style="margin:0;background:transparent">${svg}</body></html>`);
const png = await page.locator("svg").screenshot({ omitBackground: true });
await browser.close();
writeFileSync(out, png);
console.log(`wrote ${out} (${png.length} bytes)`);
