// Find identifiers a module uses but never imports or defines.
//
// `vite build` does not catch this. An unresolved bare identifier is a perfectly valid
// reference to a global as far as the bundler is concerned, so a missing import compiles
// cleanly and then throws "X is not defined" the moment the component renders -- a blank page,
// found only by opening the app. That has now happened twice: once when a constant moved
// modules, and once when an added import silently failed to apply because the line it was
// anchored to was spelled slightly differently ("../lib/api" vs "../lib/api.js").
//
// Scope is deliberately narrow, because narrow is what makes it trustworthy: hook calls
// (useSomething(...)) and JSX elements (<Something ...>). Both are unambiguous -- they name a
// binding that must exist in the module -- so there is nothing to tune and no false positives
// to learn to ignore.
//
//     node tools/check-undefined.mjs        (exits 1 on a finding)

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

// Things that are legitimately not module-scope bindings.
const GLOBALS = new Set([
  "Fragment", "React", "Suspense", "StrictMode", "Profiler",
  "Object", "Array", "Math", "JSON", "Date", "Number", "String", "Boolean", "Error",
  "Map", "Set", "Promise", "RegExp", "Intl", "Image", "FileReader", "Blob", "URL",
  "Event", "Audio", "AbortController", "WebSocket", "EventSource", "Notification",
]);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.jsx?$/.test(p)) out.push(p);
  }
  return out;
}

// Names this module binds at its top level: imports, declarations, functions, classes.
function bindings(src) {
  const names = new Set();
  const add = (s) => { if (s) for (const n of s.split(",")) names.add(n.trim().split(/\s+as\s+/).pop().trim()); };

  for (const m of src.matchAll(/^\s*import\s+([^;]+?)\s+from\s+["'][^"']+["']/gm)) {
    const clause = m[1];
    const braced = clause.match(/\{([^}]*)\}/);
    if (braced) add(braced[1]);
    const bare = clause.replace(/\{[^}]*\}/, "").replace(/^\s*,|,\s*$/g, "").trim();
    if (bare) add(bare.replace(/^\*\s+as\s+/, ""));
  }
  for (const m of src.matchAll(/^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) names.add(m[1]);
  for (const m of src.matchAll(/^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/gm)) names.add(m[1]);
  for (const m of src.matchAll(/^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)/gm)) names.add(m[1]);
  // Locally destructured or assigned names anywhere -- conservative, to avoid false alarms.
  for (const m of src.matchAll(/(?:const|let|var)\s*\[([^\]]*)\]/g)) add(m[1]);
  for (const m of src.matchAll(/(?:const|let|var)\s*\{([^}]*)\}/g)) add(m[1].replace(/:[^,]*/g, ""));
  return names;
}

// Browser built-ins that look like state setters.
const SETTER_GLOBALS = new Set(["setTimeout", "setInterval", "setImmediate"]);

let bad = 0;
for (const file of walk(ROOT)) {
  const src = readFileSync(file, "utf8");
  const have = bindings(src);
  const used = new Map();
  for (const m of src.matchAll(/\b(use[A-Z][\w$]*)\s*\(/g)) used.set(m[1], "hook");
  for (const m of src.matchAll(/<([A-Z][\w$]*)[\s/>]/g)) used.set(m[1], "component");
  // State setters. `setDropped` was called in FlashButton's flash handler while the matching
  // useState was never written, so every real flash threw AFTER the device had been written --
  // the keyboard took the changes and the UI reported a failure. Neither check above catches
  // that: a setter is not a hook and not a component. `bindings()` already collects
  // destructured and imported names, so a real setter is found there.
  // The lookbehind matters: `\b` also fires after a dot, so `api.setBaseLayer(...)` and any
  // other method call would read as a bare identifier and produce noise.
  for (const m of src.matchAll(/(?<![.\w$])(set[A-Z][\w$]*)\s*\(/g)) {
    if (!SETTER_GLOBALS.has(m[1])) used.set(m[1], "state setter");
  }

  for (const [name, kind] of used) {
    if (have.has(name) || GLOBALS.has(name)) continue;
    console.error(`${relative(ROOT, file)}: ${kind} \`${name}\` is used but never imported or defined`);
    bad++;
  }
}

if (bad) {
  console.error(`\n${bad} undefined reference(s) -- these render as a blank page, not a build error.`);
  process.exit(1);
}
console.log("no undefined hook, component or state-setter references");
