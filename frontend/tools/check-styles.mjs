// Style budget: counts that may only go down.
//
// The foundation pass (Jira SCRUM-73..78) moves every colour into theme tokens, every repeated
// skin into a primitive and every native confirm() into an in-app dialog. Nothing in the build
// notices when one of those creeps back in, so this counts them per file and compares against a
// committed budget (tools/style-budget.json). A count above its budget fails; a count below it is
// printed so the budget can be lowered in the same change. Raising a budget is a diff a reviewer
// sees. Same shape and spirit as check-undefined.mjs: narrow, no configuration, no dependencies.
//
// Counted:
//   inlineStyles   style={{ ... }} in .jsx           (should be a class on a primitive)
//   colorLiterals  #hex, rgb(), rgba(), hsl() in .jsx and in .css other than theme.css
//                  (should be a var(--token); theme.css is where the literals live)
//   nativeDialogs  confirm( / alert( / prompt( across src (should be confirmDialog())
//
//     node tools/check-styles.mjs           check against the budget (exits 1 when over)
//     node tools/check-styles.mjs init      write the budget from today's counts
//     node tools/check-styles.mjs report    print today's counts

import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

const winPath = (u) => u.pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = winPath(new URL("../src", import.meta.url));
const BUDGET = winPath(new URL("./style-budget.json", import.meta.url));

// theme.css is the one place literals belong; ui.css (the primitives) must use tokens like the rest.
const LITERAL_FILES_EXEMPT = new Set(["styles/theme.css"]);

const COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(/g;
const INLINE_STYLE = /style=\{\{/g;
const NATIVE_DIALOG = /(?<![.\w$])(?:window\.)?(?:confirm|alert|prompt)\s*\(/g;

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(jsx?|css)$/.test(p)) out.push(p);
  }
  return out;
}

const count = (src, re) => (src.match(re) || []).length;

function measure() {
  const files = {};
  let nativeDialogs = 0;
  for (const file of walk(SRC)) {
    const rel = relative(SRC, file).split("\\").join("/");
    const src = readFileSync(file, "utf8");
    const m = {};
    if (rel.endsWith(".jsx")) {
      m.inlineStyles = count(src, INLINE_STYLE);
      m.colorLiterals = count(src, COLOR);
      nativeDialogs += count(src, NATIVE_DIALOG);
    } else if (rel.endsWith(".js")) {
      nativeDialogs += count(src, NATIVE_DIALOG);
      m.colorLiterals = count(src, COLOR);
    } else if (rel.endsWith(".css") && !LITERAL_FILES_EXEMPT.has(rel)) {
      m.colorLiterals = count(src, COLOR);
    }
    const nonZero = Object.fromEntries(Object.entries(m).filter(([, v]) => v > 0));
    if (Object.keys(nonZero).length) files[rel] = nonZero;
  }
  return { nativeDialogs, files };
}

const mode = process.argv[2] || "check";
const now = measure();

if (mode === "init") {
  writeFileSync(BUDGET, JSON.stringify(now, null, 2) + "\n");
  console.log(`wrote ${relative(process.cwd(), BUDGET)} from today's counts`);
  process.exit(0);
}
if (mode === "report") {
  console.log(JSON.stringify(now, null, 2));
  process.exit(0);
}

if (!existsSync(BUDGET)) {
  console.error("no tools/style-budget.json; create it with: node tools/check-styles.mjs init");
  process.exit(1);
}
const budget = JSON.parse(readFileSync(BUDGET, "utf8"));
let over = 0;
const slack = [];

const check = (label, have, allowed) => {
  if (have > allowed) {
    console.error(`${label}: ${have} (budget ${allowed}) -- move it into a token, a primitive or a dialog`);
    over++;
  } else if (have < allowed) {
    slack.push(`${label}: ${have} (budget ${allowed})`);
  }
};

check("nativeDialogs", now.nativeDialogs, budget.nativeDialogs ?? 0);
const names = new Set([...Object.keys(now.files), ...Object.keys(budget.files ?? {})]);
for (const rel of [...names].sort()) {
  const have = now.files[rel] ?? {};
  const allowed = budget.files?.[rel] ?? {};
  for (const metric of new Set([...Object.keys(have), ...Object.keys(allowed)])) {
    check(`${rel} ${metric}`, have[metric] ?? 0, allowed[metric] ?? 0);
  }
}

if (slack.length) {
  console.log("under budget (lower these in tools/style-budget.json, in their own commit):");
  for (const s of slack) console.log("  " + s);
}
if (over) {
  console.error(`\n${over} style budget(s) exceeded.`);
  process.exit(1);
}
console.log("style budgets hold");
