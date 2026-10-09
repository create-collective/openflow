// End-to-end test of the in-app updater: an installed OpenFlow updates itself.
//
// Builds the app twice for this machine with `npm run build:app`: "old" at the repository's
// version and "new" at 9.9.9. Serves the new build's update file and installer from localhost,
// installs the old one the way a user would (per-user NSIS installer; the zip's .app into
// ~/Applications; the AppImage into ~/Applications), runs its hidden `--update-now` (the same
// check, download and install the Install button runs, with no window and no backend), and
// passes when the installed copy reads 9.9.9.
//
// Signing comes from the job: run scripts/ci-signing.mjs first with the release secrets, as the
// release does. That matters here: Squirrel.Mac only accepts an update signed like the app it
// replaces, and on Windows the updater checks the installer's publisher.
//
//     node scripts/updater-e2e.mjs        (on a CI runner: it installs OpenFlow for this user)
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { copyFileSync, createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RELEASE = join(ROOT, "release");
const WORK = join(process.env.RUNNER_TEMP || tmpdir(), "openflow-updater-e2e");
const SERVE = join(WORK, "serve");
const PORT = 8766;
const NEW_VERSION = "9.9.9";
const OS = process.platform;

const step = (m) => console.log(`\n== ${m} ==`);
const fail = (m) => { console.error(`FAIL: ${m}`); process.exit(1); };
const sh = (cmd, args, opts = {}) => {
  const r = spawnSync(cmd, args, { cwd: ROOT, stdio: "inherit", shell: OS === "win32", ...opts });
  if (r.status !== 0) fail(`${cmd} ${args.join(" ")} exited ${r.status}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// What to build and where the update file lands, per platform.
const TARGET = {
  win32: { args: ["--win", "nsis", "--x64"], channel: "latest.yml", installer: /-setup\.exe$/ },
  darwin: { args: ["--mac", "zip", process.arch === "arm64" ? "--arm64" : "--x64"], channel: "latest-mac.yml", installer: /\.zip$/ },
  linux: { args: ["--linux", "AppImage", "--x64"], channel: "latest-linux.yml", installer: /\.AppImage$/ },
}[OS];
if (!TARGET) fail(`no updater test for ${OS}`);

function build() {
  rmSync(RELEASE, { recursive: true, force: true });
  sh("npm", ["run", "build:app", "--", ...TARGET.args]);
  const installer = readdirSync(RELEASE).find((f) => TARGET.installer.test(f));
  if (!installer) fail(`no installer in release/ (${readdirSync(RELEASE).join(", ")})`);
  if (!existsSync(join(RELEASE, TARGET.channel))) fail(`no ${TARGET.channel} in release/`);
  return join(RELEASE, installer);
}

// The new build is the repository with __version__ 9.9.9 and the release notes the version gate
// wants; both files, and the two package.json files version:sync stamps, are put back after.
function stampVersion() {
  const files = ["backend/openflow_backend/__init__.py", "frontend/src/changelog.js", "package.json", "frontend/package.json"];
  const saved = Object.fromEntries(files.map((f) => [f, readFileSync(join(ROOT, f), "utf8")]));
  const init = join(ROOT, files[0]);
  writeFileSync(init, saved[files[0]].replace(/^__version__\s*=\s*"[^"]+"/m, `__version__ = "${NEW_VERSION}"`));
  const changelog = join(ROOT, files[1]);
  // A Windows checkout has CRLF line ends.
  writeFileSync(changelog, saved[files[1]].replace(/const CHANGELOG = \[(\r?\n)/,
    (_, eol) => `const CHANGELOG = [${eol}  { version: "${NEW_VERSION}", date: "2026-01-01", notes: ["updater end-to-end test"] },${eol}`));
  sh("npm", ["run", "version:sync"]);
  return () => { for (const [f, text] of Object.entries(saved)) writeFileSync(join(ROOT, f), text); };
}

function serve() {
  const server = createServer((req, res) => {
    const file = join(SERVE, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/^\/+/, ""));
    if (!file.startsWith(SERVE) || !existsSync(file) || statSync(file).isDirectory()) {
      res.writeHead(404).end();
      return;
    }
    console.log(`  served ${basename(file)}`);
    res.writeHead(200, { "content-length": statSync(file).size });
    createReadStream(file).pipe(res);
  });
  return new Promise((r) => server.listen(PORT, "127.0.0.1", () => r(server)));
}

// Where a user's install lives, how to put the old build there, and what version it reads.
const INSTALL = {
  win32: {
    exe: join(process.env.LOCALAPPDATA || "", "Programs", "OpenFlow", "OpenFlow.exe"),
    install(installer) {
      // Per-user and silent, as the NSIS installer does for an update. spawnSync waits for the
      // installer itself, not for anything it starts.
      const r = spawnSync(installer, ["/S"], { stdio: "inherit" });
      if (r.status !== 0) fail(`the old installer exited ${r.status}`);
    },
    version() {
      if (!existsSync(this.exe)) return null;
      // Windows keeps four parts ("0.6.0.0"); the app's version is the first three.
      const v = execFileSync("powershell", ["-NoProfile", "-Command", `(Get-Item -LiteralPath '${this.exe}').VersionInfo.ProductVersion`], { encoding: "utf8" }).trim();
      return v.split(".").slice(0, 3).join(".");
    },
  },
  darwin: {
    app: join(homedir(), "Applications", "OpenFlow.app"),
    get exe() { return join(this.app, "Contents", "MacOS", "OpenFlow"); },
    install(zip) {
      mkdirSync(dirname(this.app), { recursive: true });
      rmSync(this.app, { recursive: true, force: true });
      sh("ditto", ["-x", "-k", zip, dirname(this.app)]);
    },
    version() {
      const plist = join(this.app, "Contents", "Info.plist");
      if (!existsSync(plist)) return null;
      return execFileSync("/usr/libexec/PlistBuddy", ["-c", "Print :CFBundleShortVersionString", plist], { encoding: "utf8" }).trim();
    },
  },
  linux: {
    exe: join(homedir(), "Applications", "OpenFlow.AppImage"),
    install(appImage) {
      mkdirSync(dirname(this.exe), { recursive: true });
      copyFileSync(appImage, this.exe);
      spawnSync("chmod", ["+x", this.exe]);
    },
    // An AppImage carries no readable version; the updater replaces the file, so compare bytes
    // with the new build.
    version() {
      if (!existsSync(this.exe)) return null;
      return readFileSync(this.exe).equals(readFileSync(join(SERVE, newInstallerName))) ? NEW_VERSION : "old";
    },
  },
}[OS];

let newInstallerName = "";

async function main() {
  rmSync(WORK, { recursive: true, force: true });
  mkdirSync(SERVE, { recursive: true });
  const oldVersion = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")).version;

  step(`old build (${oldVersion})`);
  const oldInstaller = join(WORK, basename(build()));
  copyFileSync(join(RELEASE, basename(oldInstaller)), oldInstaller);

  step(`new build (${NEW_VERSION})`);
  const restore = stampVersion();
  let newInstaller;
  try { newInstaller = build(); } finally { restore(); }
  newInstallerName = basename(newInstaller);
  // The update file names its installer by a relative url, so both go in one folder; the
  // blockmap lets the updater download a difference instead of the whole file where it can.
  for (const f of readdirSync(RELEASE)) {
    if (f === TARGET.channel || f === newInstallerName || f === `${newInstallerName}.blockmap`) copyFileSync(join(RELEASE, f), join(SERVE, f));
  }
  console.log(readFileSync(join(SERVE, TARGET.channel), "utf8"));

  step("serve on localhost");
  const server = await serve();

  step(`install old (${oldVersion})`);
  INSTALL.install(oldInstaller);
  const before = INSTALL.version();
  if (OS !== "linux" && before !== oldVersion) fail(`installed copy reads ${before}, expected ${oldVersion}`);
  console.log(`installed: ${INSTALL.exe} (${before})`);

  step("update through OpenFlow --update-now");
  const env = { ...process.env, OPENFLOW_UPDATE_URL: `http://127.0.0.1:${PORT}/` };
  const launcher = OS === "linux" ? ["xvfb-run", ["-a", INSTALL.exe, "--update-now"]] : [INSTALL.exe, ["--update-now"]];
  const app = spawn(launcher[0], launcher[1], { env, stdio: "inherit", detached: OS !== "win32" });
  app.on("exit", (code) => console.log(`  OpenFlow --update-now exited ${code}`));
  let now = null;
  for (let i = 0; i < 120 && now !== NEW_VERSION; i++) {
    await sleep(3000);
    try { now = INSTALL.version(); } catch { now = null; }   // mid-swap the files can be absent
  }
  server.close();
  if (now !== NEW_VERSION) fail(`the installed copy still reads ${now} after 6 minutes`);
  console.log(`PASS: ${oldVersion} updated itself to ${NEW_VERSION}`);

  // macOS relaunches the updated app; leave nothing running on the runner.
  if (OS === "darwin") spawnSync("pkill", ["-f", "OpenFlow.app"]);
  if (OS === "win32") spawnSync("taskkill", ["/IM", "OpenFlow.exe", "/T", "/F"]);
  process.exit(0);
}

main().catch((e) => fail(e.stack || e.message));
