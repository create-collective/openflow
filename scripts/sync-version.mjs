// One version number: backend/openflow_backend/__init__.py's __version__.
//
// It is what the running app reports (/api/info/system), what Settings compares against GitHub
// releases, and what pyproject.toml reads (dynamic version). The two package.json files (the app
// at the root, the renderer in frontend/) are stamped from it here; nothing else carries a copy.
//
//     npm run version:sync           stamp package.json and frontend/package.json
//     npm run version:check          exit 1 if either drifted (runs inside build:app and in CI)
//
// To release: edit __version__, npm run version:sync, commit, tag openflow-v<version>.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const check = process.argv.includes("--check");

const init = readFileSync(resolve(ROOT, "backend/openflow_backend/__init__.py"), "utf8");
const m = init.match(/^__version__\s*=\s*"(\d+\.\d+\.\d+(?:[-+][\w.]+)?)"\s*$/m);
if (!m) {
  console.error("sync-version: no __version__ = \"x.y.z\" line in backend/openflow_backend/__init__.py");
  process.exit(1);
}
const version = m[1];

let drift = 0;
for (const rel of ["package.json", "frontend/package.json"]) {
  const file = resolve(ROOT, rel);
  const text = readFileSync(file, "utf8");
  const pkg = JSON.parse(text);
  if (pkg.version === version) continue;
  if (check) {
    console.error(`sync-version: ${rel} has ${pkg.version}, __version__ is ${version} (run npm run version:sync)`);
    drift++;
    continue;
  }
  const eol = text.includes("\r\n") ? "\r\n" : "\n";
  writeFileSync(file, JSON.stringify({ ...pkg, version }, null, 2).replace(/\n/g, eol) + eol);
  console.log(`sync-version: ${rel} ${pkg.version} -> ${version}`);
}
if (drift) process.exit(1);
console.log(`sync-version: ${version}${check ? " everywhere" : ""}`);
