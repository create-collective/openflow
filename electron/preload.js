// Exposes the backend port to the renderer, matching NayaFlow's contract:
//   window.EXPOSED.bgServerPort
// The port is the second-to-last argv entry (Electron appends "/prefetch:1"),
// which is exactly how NayaFlow's preload.mjs read it.

//
// And OpenFlow's own updates (electron/updater.js) as window.openflowUpdates: the page asks, the
// shell checks, downloads and installs. Absent in a plain browser (the Vite dev server, tests).

const { contextBridge, ipcRenderer } = require("electron");

const args = process.argv.filter((a) => a !== "/prefetch:1");
const bgServerPort = parseInt(args[args.length - 1], 10) || 3001;

contextBridge.exposeInMainWorld("EXPOSED", { bgServerPort });

const subscribe = (channel) => (cb) => {
  const handler = (_event, payload) => cb(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
};

contextBridge.exposeInMainWorld("openflowUpdates", {
  state: () => ipcRenderer.invoke("updates:state"),
  setCheck: (on) => ipcRenderer.invoke("updates:set-check", !!on),
  check: () => ipcRenderer.invoke("updates:check"),
  install: () => ipcRenderer.invoke("updates:install"),
  onProgress: subscribe("updates:progress"),
  onAvailable: subscribe("updates:available"),
});
