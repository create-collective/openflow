// OpenFlow desktop shell.
//
// Mirrors NayaFlow's process model: the main process starts a backend on a localhost port and
// hands the port to the renderer through the preload (window.EXPOSED.bgServerPort). Here the
// backend is the Python openflow_backend: in development the package from the backend venv
// (OPENFLOW_DEV=1, renderer from the Vite dev server), in the packaged app the frozen sidecar
// under resources/backend, which also serves the built renderer at http://127.0.0.1:<port>/ so
// page and API share one origin.
//
// What the shell guarantees:
//   * the backend it talks to is its own: every launch mints a token (OPENFLOW_INSTANCE) and
//     the window opens only once /api/info/system echoes it back;
//   * the port is 3001 when free (localStorage is keyed by origin+port, so a stable port keeps
//     the renderer's remembered profile and layout across launches), else an ephemeral one;
//   * Chromium's own files stay out of the backend's data dir (userData moves to .../shell);
//   * one instance; a second launch focuses the first;
//   * a clean stop: /rpc/shutdown with the token (the backend closes the keyboard's port),
//     then the process tree is killed if it has not gone within two seconds;
//   * the sidecar's output lands in <data dir>/logs/sidecar.log, named in the error dialog when
//     the backend fails to start or dies;
//   * an update installs only on a click and never during a flash (electron/updater.js).

const { app, BrowserWindow, Menu, dialog, screen, shell } = require("electron");
const { spawn, spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const { setupUpdates } = require("./updater");

const DEV = process.env.OPENFLOW_DEV === "1";
const PREFERRED_PORT = 3001;
const INSTANCE = crypto.randomUUID();
const READY_TIMEOUT_MS = 30_000;      // PyInstaller cold start plus antivirus can take seconds

let backendProc = null;
let backendPort = null;
let win = null;
let quitting = false;
let backendStopped = false;

// Mirrors backend/openflow_backend/config.py data_dir(); keep the two in step.
function dataDir() {
  if (process.env.OPENFLOW_DATA_DIR) return process.env.OPENFLOW_DATA_DIR;
  if (process.platform === "win32") return path.join(process.env.APPDATA || os.homedir(), "OpenFlow");
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "OpenFlow");
  return path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "OpenFlow");
}

// Chromium's cache, Local Storage and Preferences live in <data dir>/shell: apart from the
// backend's user-data.db, backups/ and logs/ (Electron's default userData is that very
// directory on Windows and macOS), and following OPENFLOW_DATA_DIR like the backend does. Must
// precede the single-instance lock: its lock file lives in userData.
app.setPath("userData", path.join(dataDir(), "shell"));
// Windows keys the taskbar button by this id. The packaged build gets it from electron-builder
// (appId); unpackaged, the app had none and the button wore the electron.exe icon whatever the
// window carried.
app.setAppUserModelId("io.github.traviswye.openflow");

function sidecarLogPath() {
  return path.join(dataDir(), "logs", "sidecar.log");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findFreePort(preferred) {
  const tryPort = (p) => new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", () => resolve(null));
    srv.listen(p, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
  return tryPort(preferred).then((p) => p ?? tryPort(0));
}

function httpJson(method, url, body, timeoutMs = 2000) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = http.request(url, {
      method,
      headers: data ? { "content-type": "application/json", "content-length": Buffer.byteLength(data) } : {},
      timeout: timeoutMs,
    }, (res) => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", (c) => { text += c; });
      res.on("end", () => {
        try { resolve({ status: res.statusCode, json: JSON.parse(text) }); }
        catch { resolve({ status: res.statusCode, json: null }); }
      });
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

function sidecarCommand(port) {
  if (DEV) {
    const backendDir = path.join(__dirname, "..", "backend");
    const py = process.platform === "win32"
      ? path.join(backendDir, ".venv", "Scripts", "python.exe")
      : path.join(backendDir, ".venv", "bin", "python");
    return { cmd: py, args: ["-m", "openflow_backend", String(port)], cwd: backendDir };
  }
  const exe = path.join(process.resourcesPath, "backend",
    process.platform === "win32" ? "openflow-backend.exe" : "openflow-backend");
  return { cmd: exe, args: [String(port)], cwd: path.dirname(exe) };
}

function startBackend(port) {
  const { cmd, args, cwd } = sidecarCommand(port);
  const logPath = sidecarLogPath();
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  try { fs.renameSync(logPath, logPath.replace(/\.log$/, ".prev.log")); } catch {}
  // A file descriptor, not a pipe: a pipe nobody reads blocks the child after 64 KB.
  const fd = fs.openSync(logPath, "a");
  fs.writeSync(fd, `[shell] ${new Date().toISOString()} starting ${cmd} ${args.join(" ")} (instance ${INSTANCE})\n`);
  backendProc = spawn(cmd, args, {
    cwd,
    env: { ...process.env, OPENFLOW_INSTANCE: INSTANCE, OPENFLOW_BACKEND_PORT: String(port) },
    stdio: ["ignore", fd, fd],
    windowsHide: true,
  });
  backendProc.on("exit", (code, signal) => {
    fs.writeSync(fd, `[shell] backend exited code=${code} signal=${signal}\n`);
    fs.closeSync(fd);
    if (!quitting) {
      dialog.showErrorBox("OpenFlow's backend stopped",
        `The backend process exited unexpectedly (code ${code ?? signal}).\n\nSee ${logPath}`);
      app.exit(1);
    }
  });
  backendProc.on("error", (err) => {
    fs.writeSync(fd, `[shell] failed to start: ${err}\n`);
  });
}

async function waitForBackend(port) {
  const url = `http://127.0.0.1:${port}/api/info/system`;
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (backendProc && backendProc.exitCode !== null) return false;
    try {
      const { status, json } = await httpJson("GET", url, null, 1000);
      // Only OUR backend counts: something else on the port answers, but not with our token.
      if (status === 200 && json && json.app === "OpenFlow" && json.instance === INSTANCE) return true;
    } catch {}
    await sleep(250);
  }
  return false;
}

async function stopBackend() {
  if (backendStopped) return;
  backendStopped = true;
  if (!backendProc || backendProc.exitCode !== null) return;
  try {
    await httpJson("POST", `http://127.0.0.1:${backendPort}/rpc/shutdown`, { instance: INSTANCE }, 2000);
  } catch {}
  const deadline = Date.now() + 2000;
  while (backendProc.exitCode === null && Date.now() < deadline) await sleep(100);
  if (backendProc.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(backendProc.pid), "/T", "/F"], { windowsHide: true });
  } else {
    backendProc.kill("SIGTERM");
    await sleep(1000);
    if (backendProc.exitCode === null) backendProc.kill("SIGKILL");
  }
}

function buildMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac ? [{ role: "appMenu" }] : [{ role: "fileMenu" }]),
    { role: "editMenu" },            // copy and paste in the renderer need these roles on macOS
    { role: "viewMenu" },            // reload and devtools: the error boundary asks for a reload
    ...(isMac ? [{ role: "windowMenu" }] : []),
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow(port) {
  const pageOrigin = DEV ? "http://localhost:5173" : `http://127.0.0.1:${port}`;
  // 1960 x 1150 by default (the owner's call, 2026-09-17): the Bindings page at 1x with room
  // around it. On a smaller display, the work area instead, so the window is never born
  // larger than the screen.
  const area = screen.getPrimaryDisplay().workAreaSize;
  win = new BrowserWindow({
    width: Math.min(1960, area.width),
    height: Math.min(1150, area.height),
    minWidth: 1100,
    minHeight: 720,
    show: false,                     // shown on ready-to-show, so no white flash and no blank window
    title: "OpenFlow",
    // The window and taskbar icon. The packaged build gets it from electron-builder; in dev
    // mode nothing else sets it and the window wore the Electron default.
    icon: path.join(__dirname, "..", "build", "icon.png"),
    backgroundColor: "#0e0e11",      // the dark theme's --bg: what shows before the page paints
    autoHideMenuBar: true,           // native frame; the menu is there behind Alt
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [String(port)],   // the preload reads the port from argv, as NayaFlow's did
    },
  });
  win.once("ready-to-show", () => win.show());
  win.on("closed", () => { win = null; });

  // Links leave for the system browser; the window never navigates away from the app.
  const external = (url) => { if (/^https?:/i.test(url)) shell.openExternal(url); };
  win.webContents.setWindowOpenHandler(({ url }) => { external(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(pageOrigin)) { event.preventDefault(); external(url); }
  });

  if (DEV) {
    win.loadURL(`${pageOrigin}/`);
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadURL(`${pageOrigin}/`);
  }
}

// The backend's answer to "may OpenFlow close for an update now?". No answer counts as no: a
// flash cannot be ruled out.
async function updateSafe() {
  try {
    const { status, json } = await httpJson("GET", `http://127.0.0.1:${backendPort}/api/update-safe`, null, 3000);
    if (status === 200 && json && typeof json.safe === "boolean") return json;
  } catch {}
  return { safe: false, reason: "OpenFlow's backend did not answer; try again in a moment." };
}

// `--update-now`: check, download and install with no window and no backend, then exit. For
// the updater test (scripts/updater-e2e.mjs); the window's Install button runs the same code.
async function updateNow() {
  backendStopped = true;
  const updates = setupUpdates({
    dataDir, getWindow: () => null,
    updateSafe: async () => ({ safe: true, reason: null }),
    stopBackend: async () => {},
  });
  const found = await updates.check().catch((e) => ({ error: e.message }));
  if (found.error || !found.available) {
    updates.log(`--update-now: ${found.error || "nothing to install"}`);
    app.exit(found.error ? 1 : 0);
    return;
  }
  const r = await updates.install({ silent: true, restart: false });
  if (!r.installing) {
    updates.log(`--update-now: ${r.error || r.blocked}`);
    app.exit(1);
  }
}

async function start() {
  if (process.argv.includes("--update-now")) return updateNow();
  buildMenu();
  backendPort = await findFreePort(PREFERRED_PORT);
  startBackend(backendPort);
  const ready = await waitForBackend(backendPort);
  if (!ready) {
    quitting = true;
    dialog.showErrorBox("OpenFlow could not start its backend",
      `No answer from the backend within ${READY_TIMEOUT_MS / 1000} seconds.\n\nSee ${sidecarLogPath()}`);
    await stopBackend();
    app.exit(1);
    return;
  }
  setupUpdates({
    dataDir,
    getWindow: () => win,
    updateSafe,
    // Closing for an install is a quit like any other: no "backend stopped" dialog.
    stopBackend: () => { quitting = true; return stopBackend(); },
  });
  createWindow(backendPort);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(start);

  app.on("activate", () => {
    // macOS: the dock icon recreates the window; the backend kept running.
    if (win === null && backendPort !== null && !quitting) createWindow(backendPort);
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", (event) => {
    quitting = true;
    if (!backendStopped) {
      event.preventDefault();
      stopBackend().finally(() => app.quit());
    }
  });

  // A signal is a quit too. Without these, SIGTERM or SIGINT (pkill, Ctrl+C in the terminal that
  // launched an AppImage, that terminal closing) ended the shell without before-quit and orphaned
  // the backend, still holding the keyboard's ports (seen in a Linux launch test, 2026-09-18).
  // On Linux that is worse than a stray process: POSIX serial ports are not exclusive the way
  // COM ports are, so the next launch's backend could open the same port alongside it.
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => app.quit());
}
