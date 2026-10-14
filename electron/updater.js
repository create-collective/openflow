// In-app updates: electron-updater, reading the GitHub releases of create-collective/openflow.
//
// The same contract as Create Companion's: nothing is checked until the user has said yes once
// (Hub asks; Settings › About changes it), then one look a week; downloading and installing
// happen only on a click. A check fetches the latest release's latest.yml, a few hundred bytes
// naming the version and its files; nothing about the user or the keyboard is sent. A DRAFT
// release is invisible to it, so a build reaches installed copies only once it is published.
//
// What cannot replace itself: the portable Windows exe, a .deb install and a development run.
// Those still learn about a new version and get a link to the release.
//
// Installing quits OpenFlow, which ends the backend, and a flash cut off that way can leave a
// half that will not boot. So the backend is asked first (/api/update-safe) and again after the
// download, and the backend is stopped before the installer starts: on Windows the installer
// runs while the app is closing, and must not find the backend's files still in use.

const { app, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const TICK_MS = 60 * 60 * 1000;          // how often to see whether the weekly look is due
const FIRST_DELAY_MS = 60 * 1000;        // the first look waits until startup has settled
const RELEASES_URL = "https://github.com/create-collective/openflow/releases/latest";

// "1.2.3" > "1.2.0"; a pre-release sorts before its release; anything else is never newer.
function newer(candidate, current) {
  const parse = (v) => {
    const m = /^v?(\d+)\.(\d+)\.(\d+)(?:-([\w.]+))?/.exec(String(v || "").trim());
    return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] ? 0 : 1] : null;
  };
  const a = parse(candidate), b = parse(current);
  if (!a || !b) return false;
  for (let i = 0; i < 4; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}

// Why this copy cannot replace itself, or null when it can.
function unsupportedReason() {
  if (!app.isPackaged) return "a development run";
  if (process.env.PORTABLE_EXECUTABLE_DIR) return "the portable build";
  if (process.platform === "linux" && !process.env.APPIMAGE) return "a package install (.deb)";
  return null;
}

function notesText(notes) {
  if (!notes) return null;
  if (typeof notes === "string") return notes.replace(/<[^>]+>/g, "").trim() || null;
  return notes.map((n) => n.note || "").join("\n").replace(/<[^>]+>/g, "").trim() || null;
}

/**
 * Wire the updater into the shell.
 *   dataDir()      the app's data folder (main.js)
 *   getWindow()    the window to send update events to, or null
 *   updateSafe()   resolves { safe, reason } from the backend
 *   stopBackend()  resolves once the backend has stopped
 */
function setupUpdates({ dataDir, getWindow, updateSafe, stopBackend }) {
  const prefsPath = path.join(dataDir(), "shell", "updates.json");
  const logPath = path.join(dataDir(), "logs", "updater.log");
  const unsupported = unsupportedReason();
  let updater = null;
  let downloaded = null;          // the version whose installer is on disk
  let busy = false;

  const log = (msg) => {
    try {
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      fs.appendFileSync(logPath, `${new Date().toISOString()} ${msg}\n`);
    } catch { /* logging never breaks an update */ }
  };
  const readPrefs = () => {
    try { return JSON.parse(fs.readFileSync(prefsPath, "utf8")); } catch { return {}; }
  };
  const writePrefs = (p) => {
    try {
      fs.mkdirSync(path.dirname(prefsPath), { recursive: true });
      fs.writeFileSync(prefsPath, JSON.stringify(p, null, 2));
    } catch (e) { log(`could not save ${prefsPath}: ${e.message}`); }
  };
  const send = (channel, payload) => {
    const w = getWindow();
    if (w && !w.isDestroyed()) w.webContents.send(channel, payload);
  };

  function getUpdater() {
    if (updater) return updater;
    const { autoUpdater } = require("electron-updater");
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = false;
    autoUpdater.allowPrerelease = false;
    autoUpdater.logger = {
      info: (m) => log(String(m)), warn: (m) => log(`warn ${m}`),
      error: (m) => log(`error ${m}`), debug: () => {},
    };
    // The updater test serves a release from localhost; nothing else sets this.
    if (process.env.OPENFLOW_UPDATE_URL) {
      autoUpdater.setFeedURL({ provider: "generic", url: process.env.OPENFLOW_UPDATE_URL });
    }
    autoUpdater.on("download-progress", (p) =>
      send("updates:progress", { percent: p.percent, transferred: p.transferred, total: p.total }));
    updater = autoUpdater;
    return updater;
  }

  async function check() {
    if (!app.isPackaged) {
      return { current: app.getVersion(), error: "Updates are for installed copies; this is a development run." };
    }
    const result = await getUpdater().checkForUpdates();
    const info = result && result.updateInfo;
    const prefs = readPrefs();
    writePrefs({ ...prefs, lastCheck: Date.now(), latest: info ? info.version : prefs.latest });
    const available = !!(result && result.isUpdateAvailable);
    log(`check: ${available ? `${info.version} available` : "up to date"} (running ${app.getVersion()})`);
    return {
      current: app.getVersion(),
      latest: info ? info.version : null,
      available,
      notes: info ? notesText(info.releaseNotes) : null,
      date: info ? info.releaseDate : null,
    };
  }

  // Download (once) and install. Resolves { blocked } while a flash runs, { error } on failure;
  // on success the app is already closing.
  async function install({ silent = true, restart = true } = {}) {
    if (unsupported) return { error: `This copy is ${unsupported}; download the new version from GitHub.` };
    if (busy) return { error: "An update is already being installed." };
    busy = true;
    try {
      let gate = await updateSafe();
      if (!gate.safe) return { blocked: gate.reason };
      const u = getUpdater();
      if (!downloaded) {
        const found = await u.checkForUpdates();
        if (!found || !found.isUpdateAvailable) return { error: "There is no newer version to install." };
        await u.downloadUpdate();
        downloaded = found.updateInfo.version;
        log(`downloaded ${downloaded}`);
      }
      // A flash may have started while the download ran.
      gate = await updateSafe();
      if (!gate.safe) return { blocked: gate.reason };
      log(`installing ${downloaded}: stopping the backend first`);
      await stopBackend();
      u.quitAndInstall(silent, restart);
      return { installing: downloaded };
    } catch (e) {
      log(`install failed: ${e.stack || e.message}`);
      return { error: e.message };
    } finally {
      busy = false;
    }
  }

  // The weekly look, once the user has said yes. A version found earlier is offered again at
  // every launch without asking the network.
  async function tick() {
    const prefs = readPrefs();
    if (prefs.check !== true || !app.isPackaged) return;
    const due = !prefs.lastCheck || Date.now() - prefs.lastCheck >= WEEK_MS || Date.now() < prefs.lastCheck;
    if (due) {
      try {
        const r = await check();
        if (r.available) send("updates:available", { version: r.latest });
      } catch (e) {
        log(`weekly check failed, will retry: ${e.message}`);
      }
    } else if (newer(prefs.latest, app.getVersion())) {
      send("updates:available", { version: prefs.latest });
    }
  }

  ipcMain.handle("updates:state", () => {
    const prefs = readPrefs();
    return {
      current: app.getVersion(),
      check: prefs.check,                      // undefined until the user has answered
      known: prefs.check === true && newer(prefs.latest, app.getVersion()) ? prefs.latest : null,
      canInstall: !unsupported,
      unsupported,
      releasesUrl: RELEASES_URL,
    };
  });
  ipcMain.handle("updates:set-check", (_e, on) => {
    writePrefs({ ...readPrefs(), check: !!on });
    log(`weekly check ${on ? "on" : "off"}`);
    if (on) tick();
    return true;
  });
  ipcMain.handle("updates:check", async () => {
    try { return await check(); } catch (e) { log(`check failed: ${e.message}`); return { error: e.message }; }
  });
  ipcMain.handle("updates:install", () => install());

  setTimeout(() => { tick(); setInterval(tick, TICK_MS); }, FIRST_DELAY_MS);

  return { check, install, log };
}

module.exports = { setupUpdates, newer };
