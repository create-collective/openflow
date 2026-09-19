// Publish a build's installers to Cloudflare R2 for the beta testers, by hand.
//
// WHY NOT A GITHUB RELEASE. Actions artifacts need repo access and expire; a release on a
// private repo needs repo access too; a release on a public repo is genuinely public, and our
// installers carry the bug-report webhook baked in (resources/report-sink.json), so publishing
// them openly hands that endpoint to anyone. R2 with an unguessable prefix gives link-only
// access without adding six people to the repo.
//
// NOT part of the release workflow on purpose: not every build should reach testers. Run it
// when you decide a build is worth handing out.
//
//     node scripts/publish-beta.mjs --run <actions-run-id> [--prefix <existing>] [--dry-run]
//
// Needs: gh (authenticated), and CLOUDFLARE_API_TOKEN + R2_BUCKET + R2_PUBLIC_BASE in the
// environment. wrangler is fetched by npx, so there is nothing to install.
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtempSync, readdirSync, statSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, basename } from "node:path";

const args = process.argv.slice(2);
const flag = (name, fallback = null) => {
  const i = args.indexOf(name);
  return i === -1 ? fallback : args[i + 1];
};
const DRY = args.includes("--dry-run");
const RUN = flag("--run");
const BUCKET = process.env.R2_BUCKET;
const PUBLIC_BASE = (process.env.R2_PUBLIC_BASE || "").replace(/\/+$/, "");

if (!RUN) {
  console.error("usage: node scripts/publish-beta.mjs --run <actions-run-id> [--prefix <p>] [--dry-run]");
  process.exit(1);
}
for (const [name, value] of [["R2_BUCKET", BUCKET], ["R2_PUBLIC_BASE", PUBLIC_BASE],
                             ["CLOUDFLARE_API_TOKEN", process.env.CLOUDFLARE_API_TOKEN]]) {
  if (!value && !DRY) {
    console.error(`publish-beta: ${name} is not set. See the header of this file.`);
    process.exit(1);
  }
}

// gh is not on PATH in this environment; take it from the usual install location if need be.
const GH = process.env.GH_PATH || "gh";
const sh = (cmd, cmdArgs, opts = {}) =>
  execFileSync(cmd, cmdArgs, { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], ...opts });

// The prefix is what makes the link unguessable. Reuse one to republish the same version
// without invalidating links already sent out; omit it for a fresh, unrelated URL.
const prefix = flag("--prefix") || randomBytes(8).toString("hex");

const dir = mkdtempSync(join(tmpdir(), "openflow-beta-"));
try {
  console.log(`downloading artifacts from run ${RUN} ...`);
  sh(GH, ["run", "download", RUN, "--dir", dir], { stdio: "inherit" });

  // Actions nests each artifact in its own directory; installers are the leaves.
  const files = [];
  const walk = (d) => {
    for (const entry of readdirSync(d)) {
      const p = join(d, entry);
      if (statSync(p).isDirectory()) walk(p);
      else files.push(p);
    }
  };
  walk(dir);

  // Ship installers and their checksums. Nothing else: a stray build log or map file published
  // under a link we hand out is still published.
  const KEEP = /\.(exe|dmg|AppImage|deb|sha256|txt)$/i;
  const chosen = files.filter((f) => KEEP.test(f));
  if (!chosen.length) {
    console.error(`publish-beta: run ${RUN} produced no installer files. Nothing uploaded.`);
    process.exit(1);
  }

  console.log(`\n${chosen.length} file(s) to publish under prefix ${prefix}/\n`);
  const links = [];
  for (const f of chosen) {
    const key = `${prefix}/${basename(f)}`;
    const mb = (statSync(f).size / 1048576).toFixed(1);
    if (DRY) {
      console.log(`  would upload  ${basename(f).padEnd(52)} ${mb.padStart(7)} MB`);
    } else {
      console.log(`  uploading     ${basename(f).padEnd(52)} ${mb.padStart(7)} MB`);
      sh("npx", ["--yes", "wrangler", "r2", "object", "put", `${BUCKET}/${key}`,
                 "--file", f, "--remote"], { stdio: "inherit" });
    }
    links.push(`${PUBLIC_BASE}/${key}`);
  }

  console.log(`\n${DRY ? "would publish" : "published"} — links for the testers:\n`);
  for (const l of links) console.log(`  ${l}`);
  console.log(`\nprefix: ${prefix}`);
  console.log("Reuse it with --prefix to replace these files without changing the links.");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
