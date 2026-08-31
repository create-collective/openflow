// OpenFlow desktop shell.
//
// Mirrors NayaFlow's process model: the main process spawns a backend on a
// localhost port and passes that port to the renderer via preload
// (window.EXPOSED.bgServerPort). Here the backend is the Python openflow_backend
// instead of flow-bg-server.exe + NayaCore.exe.

const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");

const DEV = process.env.OPENFLOW_DEV === "1";
let backendProc = null;
let win = null;

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function startBackend(port) {
  // In dev, run the module from the backend venv. In production this would be a
  // PyInstaller sidecar exe next to the app (packaged like Naya's Go server).
  const backendDir = path.join(__dirname, "..", "backend");
  const py =
    process.platform === "win32"
      ? path.join(backendDir, ".venv", "Scripts", "python.exe")
      : path.join(backendDir, ".venv", "bin", "python");

  backendProc = spawn(py, ["-m", "openflow_backend", String(port)], {
    cwd: backendDir,
    env: { ...process.env, OPENFLOW_BACKEND_PORT: String(port) },
    stdio: "inherit",
  });
  backendProc.on("exit", (code) => {
    console.log(`[openflow] backend exited with code ${code}`);
  });
}

async function waitForBackend(port, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ok = await new Promise((resolve) => {
      const s = net.connect(port, "127.0.0.1");
      s.on("connect", () => {
        s.destroy();
        resolve(true);
      });
      s.on("error", () => resolve(false));
    });
    if (ok) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

async function createWindow() {
  const port = await findFreePort();
  startBackend(port);
  await waitForBackend(port);

  win = new BrowserWindow({
    width: 1200,
    height: 800,
    backgroundColor: "#0e0e11",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      // The preload reads the port from argv, as NayaFlow's did.
      additionalArguments: [String(port)],
    },
  });

  if (DEV) {
    // Renderer served by the Vite dev server; it reads the port from preload.
    win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
  }
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (backendProc) backendProc.kill();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backendProc) backendProc.kill();
});
