// REST client for the OpenFlow backend.
// Base URL follows NayaFlow's recovered pattern: the Electron preload exposes the
// backend port on window.EXPOSED.bgServerPort; standalone dev falls back to 3001.

const bgServerPort = (window.EXPOSED && window.EXPOSED.bgServerPort) || null;
// With a port from the shell the backend is at 127.0.0.1 and, in the desktop app, is also what
// serves this page, so the API origin must be byte-identical to the page origin (localhost may
// resolve to ::1 first). Standalone in a browser tab: the backend's own default port.
export const BASE = bgServerPort ? `http://127.0.0.1:${bgServerPort}` : "http://localhost:3001";

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
  ignorePort: (port) => req("POST", "/rpc/ignore-port", { port }),
  unignorePort: (port) => req("POST", "/rpc/unignore-port", { port }),
  status: () => req("GET", "/api/status"),
  // verbose adds the BLE identity block + the pairing cross-check. Five extra round trips per
  // half, so it is opt-in: Device Manager does not need it, the Information page does.
  statusDeep: () => req("GET", "/api/status?verbose=1"),
  statusLastDeep: () => req("GET", "/api/status/last?deep=1"),
  statusLive: () => req("GET", "/api/status/live"),
  statusLast: () => req("GET", "/api/status/last"),
  diagnostics: () => req("GET", "/api/diagnostics/report"),
  releaseDevice: () => req("POST", "/rpc/release-device"),
  reconnectDevice: () => req("POST", "/rpc/reconnect-device"),
  reportContext: (identifiers = false) => req("GET", `/api/report/context?identifiers=${identifiers ? 1 : 0}`),
  reportBug: (body) => req("POST", "/rpc/report-bug", body),
  firmwareCatalog: () => req("GET", "/api/firmware-catalog"),
  // Which image each connected half would take at a given version, and whether we actually hold
  // it. Resolved by the backend from the half's product id: side and flash generation are not
  // interchangeable, and the UI must not be the thing that guesses.
  firmwareUpdatePlan: (version = "") =>
    req("GET", "/api/firmware-update-plan" + (version ? "?version=" + encodeURIComponent(version) : "")),
  // Starts the supervised firmware procedure and returns the run's opening snapshot -- it does
  // NOT wait for the flash. Progress arrives on the stream (sse:flash-progress); flashRun() is
  // the catch-up for a page that reloads mid-run.
  // acceptUnknown: the user agreed to replace firmware OpenFlow holds no copy of (and so cannot
  // put back). The backend refuses such a half without it.
  flashFirmware: (targets, allowOlder = false, acceptUnknown = false) =>
    req("POST", "/rpc/flash-procedure",
      { targets, allow_older: allowOlder, accept_unknown_running: acceptUnknown }),
  flashRun: (since = 0) => req("GET", `/api/flash-runs/current?since=${since}`),
  // Module firmware (backend device/module_procedure.py): what an update would do and what stops
  // it, read-only; then the run, which returns its opening snapshot and streams like a keyboard
  // flash. body: { version, allow_older, force_type }.
  moduleUpdatePlan: (version = "") =>
    req("GET", "/api/module-update-plan" + (version ? "?version=" + encodeURIComponent(version) : "")),
  flashModuleFirmware: (body) => req("POST", "/rpc/module-flash-procedure", body),
  // The catalogue joined against what this machine holds, and the download that closes the gap.
  // Images are not shipped with OpenFlow; each one is verified against the catalogue's sha256
  // before it is kept.
  firmwareLibrary: () => req("GET", "/api/firmware-library"),
  // Either whole versions (what the update dialog asks for) or exact catalogue paths (what the
  // library sends, having just listed them). Nothing outside the catalogue can be named.
  fetchFirmware: (body) => req("POST", "/rpc/fetch-firmware", body),
  flashLogs: () => req("GET", "/api/flash-logs"),
  flashLog: (id) => req("GET", `/api/flash-logs/${encodeURIComponent(id)}`),
  deviceLog: (limit = 200) => req("GET", `/api/device-log?limit=${limit}`),
  clearDeviceLog: () => req("POST", "/rpc/clear-device-log", {}),
  openLogsFolder: () => req("POST", "/rpc/open-logs-folder", {}),
  recoveryOps: () => req("GET", "/api/recovery-ops"),
  runRecoveryOp: (op, opts = {}, force = true) => req("POST", "/rpc/run-recovery-op", { op, opts, force }),
  pairingRepairPlan: () => req("GET", "/api/pairing-repair/plan"),
  pairingRepairVerify: () => req("GET", "/api/pairing-repair/verify"),
  pairingRepair: (arm, force = true) => req("POST", "/rpc/pairing-repair", { arm, force }),
  readKeyboard: (body = {}) => req("POST", "/rpc/read-keyboard", body),
  readModules: (body = {}) => req("POST", "/rpc/read-modules", body),
  moduleVariants: () => req("GET", "/api/module-variants"),
  createModuleProfile: (variant, name) => req("POST", "/rpc/create-module-profile", { variant, name }),
  renameModuleProfile: (configId, name) => req("POST", "/rpc/rename-module-profile", { configId, name }),
  deleteModuleProfile: (configId) => req("POST", "/rpc/delete-module-profile", { configId }),
  exportModuleProfile: (configId) => req("POST", "/rpc/export-module-profile", { configId }),
  importModuleProfile: (profile, name) => req("POST", "/rpc/import-module-profile", { profile, name }),
  // The only call that writes to the keyboard. The confirm token is required by the
  // backend, so an accidental call cannot flash.
  flash: (body = {}) => req("POST", "/rpc/flash", { confirm: "FLASH", ...body }),

  userdata: () => req("GET", "/api/userdata"),
  actions: () => req("GET", "/api/actions"),
  // Per-app chords are fetched on demand: the file is 1.2 MB and must not ride along on
  // /api/actions, which every page loads. No args = just the application list.
  appShortcuts: (p) => req("GET", "/api/app-shortcuts" + (p
    ? "?" + new URLSearchParams(Object.entries(p).filter(([, v]) => v !== "" && v != null)).toString()
    : "")),
  modules: () => req("GET", "/api/modules"),
  deviceState: () => req("GET", "/api/device-state"),
  setModuleSetting: (body) => req("POST", "/rpc/set-module-setting", body),
  setModuleBinding: (body) => req("POST", "/rpc/set-module-binding", body),
  setAxisSplit: (body) => req("POST", "/rpc/set-axis-split", body),
  setAxisInvert: (body) => req("POST", "/rpc/set-axis-invert", body),
  setLayerBay: (body) => req("POST", "/rpc/set-layer-bay", body),
  macros: () => req("GET", "/api/macros"),
  createMacro: (name) => req("POST", "/rpc/create-macro", { name }),
  deleteMacro: (id) => req("POST", "/rpc/delete-macro", { id }),
  addMacroStep: (body) => req("POST", "/rpc/add-macro-step", body),
  deleteMacroStep: (stepId) => req("POST", "/rpc/delete-macro-step", { stepId }),
  reorderMacroSteps: (macroId, orderedIds) => req("POST", "/rpc/reorder-macro-steps", { macroId, orderedIds }),
  addMacroSteps: (macroId, steps) => req("POST", "/rpc/add-macro-steps", { macroId, steps }),
  renameMacro: (macroId, name) => req("POST", "/rpc/rename-macro", { macroId, name }),
  updateMacroStep: (stepId, patch) => req("POST", "/rpc/update-macro-step", { stepId, ...patch }),
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
  setModuleLed: (body) => req("POST", "/rpc/set-module-led", body),

  led: (side, action, value) => req("POST", "/rpc/led", { side, action, value }),
  restoreLighting: (side = "left") => req("POST", "/rpc/restore-lighting", { side }),
  bleProfiles: (side = "left") => req("GET", `/api/ble/profiles?side=${side}`),
  selectBleProfile: (side, index) =>
    req("POST", "/rpc/select-ble-profile", { side, index, confirm: "SELECT" }),
  clearBleProfile: (side, index) =>
    req("POST", "/rpc/clear-ble-profile", { side, index, confirm: "CLEAR" }),
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
  // A NayaFlow database or backup zip, converted server-side and imported as new profiles.
  importProfileFile: async (file) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(BASE + "/rpc/import-profile-file", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Import failed");
    return data;
  },
  // Convert a NayaFlow .db / backup .zip to OpenFlow profile JSON, without importing it.
  convertDbToJson: async (file) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(BASE + "/rpc/convert-db-to-json", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Convert failed");
    return data;
  },
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
