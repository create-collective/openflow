// Exposes the backend port to the renderer, matching NayaFlow's contract:
//   window.EXPOSED.bgServerPort
// The port is the second-to-last argv entry (Electron appends "/prefetch:1"),
// which is exactly how NayaFlow's preload.mjs read it.

const { contextBridge } = require("electron");

const args = process.argv.filter((a) => a !== "/prefetch:1");
const bgServerPort = parseInt(args[args.length - 1], 10) || 3001;

contextBridge.exposeInMainWorld("EXPOSED", { bgServerPort });
