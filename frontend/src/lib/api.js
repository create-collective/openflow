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
  setModuleSetting: (body) => req("POST", "/rpc/set-module-setting", body),
  macros: () => req("GET", "/api/macros"),
  createMacro: (name) => req("POST", "/rpc/create-macro", { name }),
  deleteMacro: (id) => req("POST", "/rpc/delete-macro", { id }),
  addMacroStep: (body) => req("POST", "/rpc/add-macro-step", body),
  deleteMacroStep: (stepId) => req("POST", "/rpc/delete-macro-step", { stepId }),
  reorderMacroSteps: (macroId, orderedIds) => req("POST", "/rpc/reorder-macro-steps", { macroId, orderedIds }),
  createProfile: (name) => req("POST", "/rpc/create-profile", { name }),
  renameProfile: (profileId, name) => req("POST", "/rpc/rename-profile", { profileId, name }),
  duplicateProfile: (profileId) => req("POST", "/rpc/duplicate-profile", { profileId }),
  deleteProfile: (profileId) => req("POST", "/rpc/delete-profile", { profileId }),
  exportProfile: (profileId) => req("GET", `/api/export-profile?profileId=${encodeURIComponent(profileId)}`),
  importProfile: (data, name) => req("POST", "/rpc/import-profile", { data, name }),
  exportLayer: (layerId) => req("GET", `/api/export-layer?layerId=${encodeURIComponent(layerId)}`),
  importLayer: (profileId, data) => req("POST", "/rpc/import-layer", { profileId, data }),

  createLayer: (profileId, name) => req("POST", "/rpc/create-layer", { profileId, name }),
  renameLayer: (layerId, name) => req("POST", "/rpc/rename-layer", { layerId, name }),
  deleteLayer: (layerId) => req("POST", "/rpc/delete-layer", { layerId }),
  duplicateLayer: (layerId) => req("POST", "/rpc/duplicate-layer", { layerId }),
  setBaseLayer: (layerId) => req("POST", "/rpc/set-base-layer", { layerId }),
  setKeyBinding: (body) => req("POST", "/rpc/set-key-binding", body),
  clearKeyBinding: (body) => req("POST", "/rpc/clear-key-binding", body),
  setKeyColor: (body) => req("POST", "/rpc/set-key-color", body),
  fillLayerColor: (body) => req("POST", "/rpc/fill-layer-color", body),
  setLayerAnimation: (body) => req("POST", "/rpc/set-layer-animation", body),

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
