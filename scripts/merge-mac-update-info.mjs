// One latest-mac.yml for both Mac builds.
//
// The release builds macOS twice, on two runners (Apple Silicon and Intel), and each writes its
// own latest-mac.yml naming only its own files. An installed copy reads ONE latest-mac.yml and
// picks the arm64 or x64 zip from its `files` list (electron-updater's MacUpdater does that by
// the "arm64" in the file name), so the release job merges the two lists here before the files
// go on the draft release.
//
//     node scripts/merge-mac-update-info.mjs <dir>
//
// <dir> holds latest-mac-arm64.yml and latest-mac-x86_64.yml (the release workflow renames each
// row's file by `uname -m`); latest-mac.yml is written next to them and the two inputs removed.
// The format is electron-builder's own, written by machine, so it is read line by line rather
// than pulling a YAML parser into a job that installs nothing.
import { existsSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dir = process.argv[2];
if (!dir) { console.error("usage: merge-mac-update-info.mjs <dir>"); process.exit(2); }

const inputs = readdirSync(dir).filter((f) => /^latest-mac-.+\.yml$/.test(f)).sort();
if (inputs.length === 0) { console.error(`no latest-mac-*.yml in ${dir}`); process.exit(1); }

// version, the `files` entries (each a "  - url:" line and its indented fields), everything else.
function parse(text) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out = { version: null, files: [], rest: [] };
  let inFiles = false;
  for (const line of lines) {
    if (/^files:\s*$/.test(line)) { inFiles = true; continue; }
    if (inFiles && /^\s/.test(line)) {
      if (/^\s*- /.test(line)) out.files.push([line]);
      else out.files[out.files.length - 1].push(line);
      continue;
    }
    inFiles = false;
    const v = /^version:\s*(.+)$/.exec(line);
    if (v) out.version = v[1].trim();
    else if (line.trim()) out.rest.push(line);
  }
  return out;
}

const parsed = inputs.map((f) => ({ name: f, ...parse(readFileSync(join(dir, f), "utf8")) }));
const versions = new Set(parsed.map((p) => p.version));
if (versions.size !== 1 || versions.has(null)) {
  console.error(`the Mac builds disagree on the version: ${parsed.map((p) => `${p.name}=${p.version}`).join(", ")}`);
  process.exit(1);
}
const urls = new Set();
const files = [];
for (const p of parsed) {
  for (const entry of p.files) {
    const url = /url:\s*(.+)$/.exec(entry[0])?.[1].trim();
    if (!url) { console.error(`${p.name}: a files entry without a url`); process.exit(1); }
    if (urls.has(url)) continue;
    urls.add(url);
    files.push(entry);
  }
}
if (!files.some((e) => /arm64/.test(e[0])) || !files.some((e) => !/arm64/.test(e[0]))) {
  console.error(`expected files for both Apple Silicon and Intel, got: ${[...urls].join(", ")}`);
  process.exit(1);
}

// The legacy top-level path/sha512 (old updaters read only these) come from the Intel file, the
// one every Mac can run.
const legacy = parsed.find((p) => !/arm64/.test(p.name)) || parsed[0];
const text = [`version: ${[...versions][0]}`, "files:", ...files.flat(), ...legacy.rest, ""].join("\n");
writeFileSync(join(dir, "latest-mac.yml"), text);
for (const f of inputs) rmSync(join(dir, f));
console.log(`latest-mac.yml: ${[...versions][0]}, ${files.length} files from ${inputs.join(" + ")}`);
if (!existsSync(join(dir, "latest-mac.yml"))) process.exit(1);
