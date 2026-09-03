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
  readKeyboard: (body = {}) => req("POST", "/rpc/read-keyboard", body),
  readModules: (body = {}) => req("POST", "/rpc/read-modules", body),
  moduleVariants: () => req("GET", "/api/module-variants"),
  createModuleProfile: (variant, name) => req("POST", "/rpc/create-module-profile", { variant, name }),
  renameModuleProfile: (configId, name) => req("POST", "/rpc/rename-module-profile", { configId, name }),
  deleteModuleProfile: (configId) => req("POST", "/rpc/delete-module-profile", { configId }),
  // The only call that writes to the keyboard. The confirm token is required by the
  // backend, so an accidental call cannot flash.
  flash: (body = {}) => req("POST", "/rpc/flash", { confirm: "FLASH", ...body }),

  userdata: () => req("GET", "/api/userdata"),
  actions: () => req("GET", "/api/actions"),
  modules: () => req("GET", "/api/modules"),
  setModuleSetting: (body) => req("POST", "/rpc/set-module-setting", body),
  setModuleBinding: (body) => req("POST", "/rpc/set-module-binding", body),
  setLayerBay: (body) => req("POST", "/rpc/set-layer-bay", body),
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
  reorderLayers: (profileId, orderedIds) => req("POST", "/rpc/reorder-layers", { profileId, orderedIds }),
  layerReferences: (layerId) => req("GET", `/api/layer-references?layerId=${encodeURIComponent(layerId)}`),
  copyLayer: (layerId, profileId, name) => req("POST", "/rpc/copy-layer", { layerId, profileId, name }),

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

  flashPreview: (body = {}) => req("POST", "/rpc/flash-preview", body),
  moduleGestures: (types) =>
    req("GET", "/api/module-gestures" + (types ? `?types=${encodeURIComponent(types)}` : "")),

  settings: () => req("GET", "/api/settings"),
  setSetting: (key, value) => req("POST", "/rpc/set-setting", { key, value }),
  backups: () => req("GET", "/api/backups"),
  openBackupFolder: () => req("POST", "/rpc/open-backup-folder", {}),
  createBackup: () => req("POST", "/rpc/create-backup", {}),
  restoreBackup: (name) => req("POST", "/rpc/restore-backup", { name }),
  importBackupFile: async (file) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(BASE + "/rpc/import-backup-file", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Import failed");
    return data;
  },

  // The original single device-control entry point.
  sendCommand: (event, frames = [], opts = {}) =>
    req("POST", "/rpc/send-nayacore-zmq-message", {
      messages: ["command", event, ...frames],
      ...opts,
    }),
};
