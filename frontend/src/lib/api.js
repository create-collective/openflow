// REST client for the OpenFlow backend.
// Base URL follows NayaFlow's recovered pattern: the Electron preload exposes the
// backend port on window.EXPOSED.bgServerPort; standalone dev falls back to 3001.

const bgServerPort = (window.EXPOSED && window.EXPOSED.bgServerPort) || 3001;
export const BASE = `http://localhost:${bgServerPort}`;

async function req(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `${method} ${path} failed (${res.status})`);
  }
  return data;
}

export const api = {
  systemInfo: () => req("GET", "/api/info/system"),
  uiState: () => req("GET", "/api/ui/state"),
  devices: () => req("GET", "/api/devices"),
  status: () => req("GET", "/api/status"),
  diagnostics: () => req("GET", "/api/diagnostics/report"),

  userdata: () => req("GET", "/api/userdata"),
  actions: () => req("GET", "/api/actions"),
  modules: () => req("GET", "/api/modules"),
  setKeyBinding: (body) => req("POST", "/rpc/set-key-binding", body),
  clearKeyBinding: (body) => req("POST", "/rpc/clear-key-binding", body),
  setKeyColor: (body) => req("POST", "/rpc/set-key-color", body),

  led: (side, action, value) => req("POST", "/rpc/led", { side, action, value }),
  textCommand: (side, command, force = false) =>
    req("POST", "/rpc/text-command", { side, command, force }),
  dumpSettings: (side) => req("POST", "/rpc/dump-settings", { side }),
  checkForUpdates: () => req("POST", "/rpc/check-for-updates"),

  // The original single device-control entry point.
  sendCommand: (event, frames = [], opts = {}) =>
    req("POST", "/rpc/send-nayacore-zmq-message", {
      messages: ["command", event, ...frames],
      ...opts,
    }),
};
