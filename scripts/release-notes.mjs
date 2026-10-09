// The GitHub release's text for one version, from what the app itself shows: the "What's new"
// notes in frontend/src/changelog.js (the Hub's own list), under a table of which download is for
// which computer. The release job writes it to RELEASE_NOTES.md for the draft release.
//
//     node scripts/release-notes.mjs 0.8.0 > RELEASE_NOTES.md
//
// Exits 1 when changelog.js has no entry for the version (version:check refuses that build first).
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const version = (process.argv[2] || "").replace(/^openflow-v|^v/, "");
if (!/^\d+\.\d+\.\d+/.test(version)) {
  console.error("usage: release-notes.mjs <version>");
  process.exit(2);
}
const { notesFor } = await import(pathToFileURL(resolve(ROOT, "frontend/src/changelog.js")).href);
const entry = notesFor(version);
if (!entry || entry.version !== version) {
  console.error(`frontend/src/changelog.js has no entry for ${version}`);
  process.exit(1);
}

const f = (rest) => `\`OpenFlow-${version}-${rest}\``;
const notes = `## Which file do I need?

| Your computer | Download |
|---|---|
| **Windows 10 or 11** (installs for your user, updates itself) | ${f("win-x64-setup.exe")} |
| Windows, without installing (does not update itself) | ${f("win-x64-portable.exe")} |
| **Mac with Apple Silicon** (M1 and later) | ${f("mac-arm64.dmg")} |
| **Mac with Intel** | ${f("mac-x64.dmg")} |
| **Debian, Ubuntu, Mint, Pop!_OS** | ${f("linux-amd64.deb")} |
| Other Linux | ${f("linux-x86_64.AppImage")} |

You don't need the other files: \`latest*.yml\`, \`*.blockmap\` and the Mac \`.zip\` files are read by OpenFlow's in-app updater, and \`SHA256SUMS-*.txt\` hold the checksums if you want to verify a download.

Already on 0.7.0 or later? OpenFlow offers this version itself if you said yes to the weekly check, or in Settings › About. The Windows installer and portable build are signed (publisher: Travis Wye); the Mac apps are signed and notarized. On Linux the keyboard needs a udev rule: the \`.deb\` installs it, and the AppImage shows the commands on first start. See the [install guide](https://github.com/create-collective/openflow#install).

## What's new in ${version}

${entry.notes.map((n) => `- ${n}`).join("\n")}

What is still held back, and why, is in the [Roadmap](https://github.com/create-collective/openflow#roadmap). Found a problem? Use **More › Report a bug** in the app, or [open an issue](https://github.com/create-collective/openflow/issues/new/choose).
`;
process.stdout.write(notes);
