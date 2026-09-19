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

// Release notes are not optional. The Hub looks up the running version in changelog.js and
// falls back to the NEWEST entry when there is none -- so a bump without notes shows the
// previous release's notes to the user, silently and with nothing logged. Checked here
// because version:check already gates build:app and runs in CI, which makes this the one
// place a forgotten entry gets caught before a build reaches anybody.
const changelog = readFileSync(resolve(ROOT, "frontend/src/changelog.js"), "utf8");
if (!changelog.includes(`version: "${version}"`)) {
  console.error(`sync-version: frontend/src/changelog.js has no entry for ${version}.`);
  console.error("  The Hub would show the previous release's notes instead. Add one:");
  console.error(`    { version: "${version}", date: "YYYY-MM-DD", notes: [...] },`);
  process.exit(1);
}

console.log(`sync-version: ${version}${check ? " everywhere, with release notes" : ""}`);
