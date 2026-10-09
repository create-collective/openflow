// Renders the README banners (dark and light, 1600x520) and GitHub's social preview card
// (1280x640) from the vector mark in public/brand/openflow-mark.svg, into ../docs/media/. The
// layout follows Create Companion's banner (mark, name, tagline with an accent rule, platform
// line) so the two projects read as a family. Uses the Playwright Chromium the route walk
// already installs, like render-icon.mjs.
//
//     node tools/render-banner.mjs
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const mark = readFileSync(join(here, "..", "public", "brand", "openflow-mark.svg"), "utf8")
  .replace(/<!--[\s\S]*?-->/g, "");
const out = join(here, "..", "..", "docs", "media");
mkdirSync(out, { recursive: true });

// Built like Create Companion's ("Your Modules. Your Apps. Dynamic Gestures.") so the two read as
// a pair; the second line is what sets OpenFlow apart from the vendor app it replaces.
const TAGLINE = ["Your Keys. Your Layers. Your Lights.", "Offline, open source, yours."];
const PLATFORMS = "Windows  ·  macOS  ·  Linux  ·  Naya Create, Tune, Touch & Track";

const THEMES = {
  // --bg of the dark theme (electron/main.js), the mark's cyan, the wordmark white from the sheet.
  dark: { bg: "#0e0e11", ink: "#fcfcfd", muted: "#9a9aa6", accent: "#03b9c9" },
  light: { bg: "#fafafc", ink: "#18181c", muted: "#64646e", accent: "#0298a5" },
};

function page(theme, { width, height, markSize, title, tag, small }) {
  const t = THEMES[theme];
  const svg = mark.replace('width="100" height="100"', `width="${markSize}" height="${markSize}"`)
    .replace('fill="#03b9c9"', `fill="${t.accent}"`);
  return `<!doctype html><html><head><style>
    html, body { margin: 0; }
    body { width: ${width}px; height: ${height}px; background: ${t.bg}; display: flex; align-items: center;
      gap: ${Math.round(markSize * 0.42)}px; padding: 0 ${Math.round(width * 0.095)}px; box-sizing: border-box;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif; }
    h1 { margin: 0; font-size: ${title}px; font-weight: 600; color: ${t.ink}; letter-spacing: -0.01em; line-height: 1.05; }
    .tag { margin-top: ${Math.round(title * 0.16)}px; font-size: ${tag}px; color: ${t.ink}; }
    .rule { width: ${Math.round(tag * 3.4)}px; height: 5px; border-radius: 3px; background: ${t.accent};
      margin: ${Math.round(tag * 0.42)}px 0 ${Math.round(tag * 0.55)}px; }
    .sub { font-size: ${tag}px; color: ${t.muted}; }
    .small { margin-top: ${Math.round(small * 0.9)}px; font-size: ${small}px; color: ${t.muted}; white-space: pre; }
  </style></head><body>
    ${svg}
    <div>
      <h1>OpenFlow</h1>
      <div class="tag">${TAGLINE[0]}</div>
      <div class="rule"></div>
      <div class="sub">${TAGLINE[1]}</div>
      <div class="small">${PLATFORMS}</div>
    </div>
  </body></html>`;
}

const browser = await chromium.launch();
async function render(file, theme, layout) {
  const p = await browser.newPage({ viewport: { width: layout.width, height: layout.height }, deviceScaleFactor: 1 });
  await p.setContent(page(theme, layout));
  const png = await p.screenshot({ type: "png" });
  writeFileSync(join(out, file), png);
  console.log(`wrote docs/media/${file} (${png.length} bytes)`);
  await p.close();
}
const banner = { width: 1600, height: 520, markSize: 250, title: 104, tag: 38, small: 28 };
await render("banner-dark.png", "dark", banner);
await render("banner-light.png", "light", banner);
await render("social-preview.png", "dark", { width: 1280, height: 640, markSize: 230, title: 92, tag: 32, small: 23 });
await browser.close();
