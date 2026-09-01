import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { pickFile } from "../lib/files";

// Placeholder repo paths — update to the real OpenFlow / firmware repos once public.
const REPOS = {
  app: "traviswye/openflow",
  firmware: "traviswye/openflow-firmware",
};

const TABS = [
  { id: "behavior", label: "Behavior" },
  { id: "interface", label: "Interface" },
  { id: "connection", label: "Connection" },
  { id: "update", label: "Software Update" },
  { id: "backup", label: "Backup" },
  { id: "troubleshooting", label: "Troubleshooting" },
  { id: "logging", label: "Logging" },
  { id: "info", label: "Software Info" },
];

function SettingField({ f, onChange }) {
  const changed = f.kind !== "toggle" && f.default !== undefined && f.value !== f.default;
  return (
    <div className="setting">
      <div className="setting-head">
        <strong>{f.label}</strong>
        <div className="setting-ctl">
          {changed && (
            <button className="setting-reset" title={`Reset to ${f.default}${f.unit || ""}`}
              onClick={() => onChange(f.id, f.default)}>↺ Reset</button>
          )}
          {f.kind === "toggle" ? (
            <button className={"toggle" + (f.value ? " on" : "")} onClick={() => onChange(f.id, !f.value)}>
              <span className="toggle-knob" />
            </button>
          ) : f.kind === "select" ? (
            <select className="mac-input" value={f.value} onChange={(e) => onChange(f.id, e.target.value)}>
              {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <span className="setting-val">{f.value}{f.unit}</span>
          )}
        </div>
      </div>
      <div className="setting-desc">{f.desc}</div>
      {f.kind === "slider" && (
        <input
          type="range" min={f.min} max={f.max} value={f.value}
          onChange={(e) => onChange(f.id, Number(e.target.value))}
          style={{ width: "100%" }}
        />
      )}
    </div>
  );
}

function SettingsGroups({ groups, onChange }) {
  return (
    <div style={{ maxWidth: 640 }}>
      {groups.map((g) => (
        <div key={g.group} style={{ marginBottom: 28 }}>
          <h3>{g.group} {g.scope === "device" && <span className="pill">device</span>}</h3>
          <p className="page-sub" style={{ marginTop: -4 }}>{g.desc}</p>
          {g.fields.map((f) => <SettingField key={f.id} f={f} onChange={onChange} />)}
        </div>
      ))}
    </div>
  );
}

function DeviceGate({ connected, children }) {
  if (connected) return children;
  return <div className="phase-note">Connect a Naya Create over USB to use this. These actions run on the device.</div>;
}

export default function Settings() {
  const [tab, setTab] = useState("behavior");
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState([]);
  const [backups, setBackups] = useState({ backups: [], dir: "" });
  const [sys, setSys] = useState(null);
  const [update, setUpdate] = useState(null);
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, info] = await Promise.all([api.settings(), api.systemInfo()]);
      setSettings(s);
      setSys(info);
    } catch (e) { setErr(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (tab === "backup") api.backups().then(setBackups).catch(() => {});
    if (tab === "connection" || tab === "info") api.status().then((r) => setStatus(r.halves || [])).catch(() => {});
  }, [tab]);

  async function setSetting(key, value) {
    setSettings((prev) => ({
      groups: prev.groups.map((g) => ({ ...g, fields: g.fields.map((f) => f.id === key ? { ...f, value } : f) })),
    }));
    try { await api.setSetting(key, value); } catch (e) { setErr(e.message); }
  }

  const connected = status.some((h) => h.connected);

  async function run(label, fn) {
    setBusy(true); setOut(`${label}…`);
    try { const r = await fn(); setOut(`${label}:\n${JSON.stringify(r, null, 2)}`); }
    catch (e) { setOut(`${label} failed:\n${e.message}`); }
    finally { setBusy(false); }
  }

  async function checkUpdate() {
    setUpdate({ checking: true });
    try {
      const res = await fetch(`https://api.github.com/repos/${REPOS.app}/releases/latest`);
      if (!res.ok) throw new Error(res.status === 404 ? "No public releases yet" : `GitHub ${res.status}`);
      const d = await res.json();
      const latest = (d.tag_name || "").replace(/^v/, "");
      setUpdate({ latest, current: sys?.backendVersion, ahead: latest && latest !== sys?.backendVersion });
    } catch (e) { setUpdate({ error: e.message }); }
  }

  const behaviorGroups = settings?.groups.filter((g) => g.group !== "Interface") || [];
  const interfaceGroups = settings?.groups.filter((g) => g.group === "Interface") || [];

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      <div className="settings-layout">
        <div className="settings-nav">
          {TABS.map((t) => (
            <button key={t.id} className={"settings-tab" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="settings-content">
          {!settings ? <div className="empty">Loading…</div> : (
            <>
              {tab === "behavior" && <SettingsGroups groups={behaviorGroups} onChange={setSetting} />}
              {tab === "interface" && <SettingsGroups groups={interfaceGroups} onChange={setSetting} />}

              {tab === "connection" && (
                <div style={{ maxWidth: 640 }}>
                  <h3>Naya Device Connection</h3>
                  {status.length === 0 && <div className="empty">No device detected.</div>}
                  {status.map((h) => (
                    <div className="kv" key={h.port}>
                      <span className="k">{h.description}</span>
                      <span className="v">{h.connected ? (h.bleAddress || "connected") : "disconnected"}</span>
                    </div>
                  ))}
                  <h3 style={{ marginTop: 24 }}>Bluetooth Connections</h3>
                  <DeviceGate connected={connected}>
                    <div className="phase-note">BLE profile pairing (slots 1-4) — read/pair wiring lands with device testing.</div>
                  </DeviceGate>
                </div>
              )}

              {tab === "update" && (
                <div style={{ maxWidth: 640 }}>
                  <h3>Software Update</h3>
                  <div className="kv"><span className="k">OpenFlow version</span><span className="v">{sys?.backendVersion}</span></div>
                  <div className="btn-row" style={{ margin: "14px 0" }}>
                    <button className="btn primary" onClick={checkUpdate}>Check GitHub for updates</button>
                  </div>
                  {update?.checking && <div className="page-sub">Checking…</div>}
                  {update?.error && <div className="phase-note">{update.error}</div>}
                  {update?.latest && (
                    <div className="kv"><span className="k">Latest release</span>
                      <span className="v">{update.latest}{update.ahead ? " (update available)" : " (up to date)"}</span></div>
                  )}
                  <p className="page-sub" style={{ marginTop: 16 }}>
                    OpenFlow has no forced updater — this is an opt-in check against GitHub Releases.
                  </p>
                  <div className="settings-links">
                    <a href={`https://github.com/${REPOS.app}`} target="_blank" rel="noreferrer">OpenFlow on GitHub ↗</a>
                    <a href={`https://github.com/${REPOS.firmware}`} target="_blank" rel="noreferrer">Firmware on GitHub ↗</a>
                  </div>
                </div>
              )}

              {tab === "backup" && (
                <div style={{ maxWidth: 720 }}>
                  <h3>Local Backups</h3>
                  <p className="page-sub">OpenFlow auto-backs up your data every 30 minutes. Restore any snapshot below.</p>
                  <div className="btn-row" style={{ marginBottom: 8 }}>
                    <button className="btn primary" disabled={busy} onClick={() => run("Backup now", async () => { const r = await api.createBackup(); setBackups(await api.backups()); return r; })}>Backup now</button>
                    {backups.dir && (
                      <button className="btn" disabled={busy} onClick={() => run("Open backup folder", api.openBackupFolder)}>Open backup folder</button>
                    )}
                    <button className="btn" disabled={busy} onClick={async () => {
                      const f = await pickFile(".db,.zip");
                      if (!f) return;
                      if (!confirm("Import this backup as your current data? Your current data is snapshotted first.")) return;
                      run("Import backup", async () => { const r = await api.importBackupFile(f); setBackups(await api.backups()); return r; });
                    }}>Import backup file…</button>
                  </div>
                  <p className="page-sub" style={{ marginBottom: 12 }}>
                    Import a NayaFlow backup (its <code>.zip</code> or the <code>user-data.db</code> inside) — OpenFlow uses the same
                    data format, so your NayaFlow profiles, layers, colors and bindings come straight across.
                  </p>
                  {backups.dir && <div className="page-sub" style={{ marginBottom: 8 }}>Folder: <span style={{ fontFamily: "var(--font-mono)" }}>{backups.dir}</span></div>}
                  {backups.backups.length === 0 ? <div className="empty">No backups yet.</div> : backups.backups.map((b) => (
                    <div className="skp-row" key={b.name} style={{ cursor: "default" }}>
                      <span className="skp-beh">{b.kind}</span>
                      <span className="skp-act" style={{ flex: 1 }}>{b.modified} · {b.sizeKb} KB</span>
                      <button className="btn" disabled={busy} onClick={() => { if (confirm("Restore this backup? Current data is snapshotted first.")) run("Restore", () => api.restoreBackup(b.name)); }}>Restore</button>
                    </div>
                  ))}
                  {out && <pre className="settings-out">{out}</pre>}
                </div>
              )}

              {tab === "troubleshooting" && (
                <div style={{ maxWidth: 640 }}>
                  <h3>Troubleshooting <span className="pill">device</span></h3>
                  <DeviceGate connected={connected}>
                    <div className="setting">
                      <div className="setting-head"><strong>Test &amp; Repair SPI-Flash</strong>
                        <button className="btn" disabled={busy} onClick={() => run("SPI flash test", () => api.sendCommand("repair_flash", [], { side: "left" }))}>Test</button></div>
                      <div className="setting-desc">Tests Create's flash memory (read-only self-test).</div>
                    </div>
                    <div className="setting">
                      <div className="setting-head"><strong>Clear BLE Devices</strong>
                        <button className="btn danger" disabled={busy} onClick={() => { if (confirm("Clear all Bluetooth bonds?")) run("Clear BLE", () => api.sendCommand("clear_ble_devices", [], { side: "left", force: true })); }}>Clear</button></div>
                      <div className="setting-desc">Forces the Create to forget all Bluetooth connections.</div>
                    </div>
                    <div className="setting">
                      <div className="setting-head"><strong>Clear All Keymap Data</strong>
                        <button className="btn danger" disabled={busy} onClick={() => run("Clear keymap", () => api.sendCommand("clear_data", [], { side: "left", force: true }))}>Clear</button></div>
                      <div className="setting-desc">Wipes on-device keymaps (REMAP clear). Phase-2 device op.</div>
                    </div>
                  </DeviceGate>
                  {out && <pre className="settings-out">{out}</pre>}
                </div>
              )}

              {tab === "logging" && (
                <div style={{ maxWidth: 640 }}>
                  <h3>Logging &amp; Diagnostics</h3>
                  <div className="setting">
                    <div className="setting-head"><strong>Diagnostics Report</strong>
                      <button className="btn" disabled={busy} onClick={() => run("Diagnostics", api.diagnostics)}>Generate</button></div>
                    <div className="setting-desc">Collects system + device info to help debug issues.</div>
                  </div>
                  <p className="page-sub">Log-folder shortcuts are available in the desktop (Electron) build.</p>
                  {out && <pre className="settings-out">{out}</pre>}
                </div>
              )}

              {tab === "info" && (
                <div style={{ maxWidth: 640 }}>
                  <h3>Software &amp; Firmware Info</h3>
                  <div className="kv"><span className="k">OpenFlow</span><span className="v">{sys?.backendVersion}</span></div>
                  <div className="kv"><span className="k">OS</span><span className="v">{sys?.os} {sys?.arch}</span></div>
                  {status.filter((h) => h.connected).map((h) => (
                    <div key={h.port}>
                      <div className="kv"><span className="k">{h.description} firmware</span><span className="v">{h.firmwareVersion || "—"}</span></div>
                      {h.module?.firmwareVersion && <div className="kv"><span className="k">{h.module.type} module firmware</span><span className="v">{h.module.firmwareVersion}</span></div>}
                    </div>
                  ))}
                  {!connected && <p className="page-sub">Connect the keyboard to read device firmware versions.</p>}
                  <div className="settings-links" style={{ marginTop: 16 }}>
                    <a href={`https://github.com/${REPOS.app}`} target="_blank" rel="noreferrer">OpenFlow source ↗</a>
                    <a href={`https://github.com/${REPOS.firmware}`} target="_blank" rel="noreferrer">Firmware source ↗</a>
                  </div>
                  <p className="page-sub" style={{ marginTop: 12 }}>
                    Firmware is open-sourced on GitHub as images are dumped/obtained.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
