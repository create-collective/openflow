import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { applyInterfaceScaling } from "../lib/scaling";
import { pickFile, downloadJSON, safeName } from "../lib/files";
import SettingField from "../components/SettingField";
// Placeholder repo paths — update to the real OpenFlow / firmware repos once public.
const REPOS = {
  app: "traviswye/openflow",
  companion: "traviswye/create-companion",
  firmware: "traviswye/openflow-firmware",
};

const TABS = [
  { id: "behavior", label: "Behavior" },
  { id: "interface", label: "Interface" },
  { id: "backup", label: "Backup" },
  { id: "troubleshooting", label: "Troubleshooting" },
  { id: "logging", label: "Logging" },
  { id: "software", label: "Software" },
];

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
  const [companion, setCompanion] = useState(null);
  const [firmware, setFirmware] = useState(null);
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
    if (tab === "software") { api.status().then((r) => setStatus(r.halves || [])).catch(() => {}); api.firmwareCatalog().then(setFirmware).catch(() => {}); }
  }, [tab]);

  async function setSetting(key, value) {
    const apply = (v) => setSettings((prev) => ({
      groups: prev.groups.map((g) => ({ ...g, fields: g.fields.map((f) => f.id === key ? { ...f, value: v } : f) })),
    }));
    // Remember what it was, so a failed write does not leave the screen showing a value the
    // backend rejected -- which read as "saved" and is the kind of quiet lie this page has
    // already told once.
    const before = settings?.groups.flatMap((g) => g.fields).find((f) => f.id === key)?.value;
    apply(value);
    if (key === "interface_scaling") applyInterfaceScaling(value);
    try {
      await api.setSetting(key, value);
    } catch (e) {
      setErr(e.message);
      if (before !== undefined) apply(before);
    }
  }

  const connected = status.some((h) => h.connected);

  async function run(label, fn) {
    setBusy(true); setOut(`${label}…`);
    try { const r = await fn(); setOut(`${label}:\n${JSON.stringify(r, null, 2)}`); }
    catch (e) { setOut(`${label} failed:\n${e.message}`); }
    finally { setBusy(false); }
  }

  // One opt-in release check, reused for OpenFlow and Create Companion -- no forced updater.
  async function checkRelease(repo, current, setter) {
    setter({ checking: true });
    try {
      const res = await fetch(`https://api.github.com/repos/${repo}/releases/latest`);
      if (!res.ok) throw new Error(res.status === 404 ? "No public releases yet" : `GitHub ${res.status}`);
      const d = await res.json();
      const latest = (d.tag_name || "").replace(/^v/, "");
      setter({ latest, current, ahead: latest && latest !== current });
    } catch (e) { setter({ error: e.message }); }
  }
  const checkUpdate = () => checkRelease(REPOS.app, sys?.backendVersion, setUpdate);
  const checkCompanion = () => checkRelease(REPOS.companion, null, setCompanion);

  // Route by SCOPE, not by name. This was `group !== "Interface"` vs `=== "Interface"`, so
  // "OneKey Timing" landed on the Behavior tab by accident and any group added to the backend
  // later would silently land there too.
  const behaviorGroups = settings?.groups.filter((g) => g.scope === "device") || [];
  const interfaceGroups = settings?.groups.filter((g) => g.scope !== "device") || [];

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
                    <button className="btn" disabled={busy} onClick={async () => {
                      const f = await pickFile(".db,.zip");
                      if (!f) return;
                      run("Convert to JSON", async () => {
                        const r = await api.convertDbToJson(f);
                        for (const p of r.profiles) {
                          downloadJSON(`${safeName(p.profile?.name || "profile")}.json`, p);
                        }
                        return { converted: r.profiles.length, saved: r.profiles.map((p) => p.profile?.name) };
                      });
                    }}>Convert database to JSON…</button>
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

              {tab === "software" && (
                <div style={{ maxWidth: 640 }}>
                  <h3>Software &amp; Firmware</h3>

                  <div className="kv"><span className="k">OpenFlow</span><span className="v">{sys?.backendVersion}</span></div>
                  <div className="kv"><span className="k">OS</span><span className="v">{sys?.os} {sys?.arch}</span></div>
                  <div className="btn-row" style={{ margin: "10px 0" }}>
                    <button className="btn" onClick={checkUpdate}>Check OpenFlow for updates</button>
                    <button className="btn" onClick={checkCompanion}>Check Create Companion</button>
                  </div>
                  {update?.checking && <div className="page-sub">Checking OpenFlow…</div>}
                  {update?.error && <div className="phase-note">OpenFlow: {update.error}</div>}
                  {update?.latest && <div className="kv"><span className="k">OpenFlow latest</span>
                    <span className="v">{update.latest}{update.ahead ? " (update available)" : " (up to date)"}</span></div>}
                  {companion?.checking && <div className="page-sub">Checking Create Companion…</div>}
                  {companion?.error && <div className="phase-note">Create Companion: {companion.error}</div>}
                  {companion?.latest && <div className="kv"><span className="k">Create Companion latest</span>
                    <span className="v">{companion.latest}</span></div>}
                  <p className="page-sub" style={{ marginTop: 4 }}>
                    Opt-in checks against GitHub Releases. OpenFlow has no forced updater.
                  </p>

                  <h3 style={{ marginTop: 22 }}>Device firmware</h3>
                  {status.filter((h) => h.connected).map((h) => (
                    <div key={h.port}>
                      <div className="kv"><span className="k">{h.description} firmware</span><span className="v">{h.firmwareVersion || "—"}</span></div>
                      {h.module?.firmwareVersion && <div className="kv"><span className="k">{h.module.type} module firmware</span><span className="v">{h.module.firmwareVersion}</span></div>}
                    </div>
                  ))}
                  {!connected && <p className="page-sub">Connect the keyboard to read device firmware versions.</p>}
                  {firmware?.reference && (
                    <div className="kv"><span className="k">Naya ships (reference)</span>
                      <span className="v">Create {firmware.reference.createFirmware} · module {firmware.reference.moduleFirmware}</span></div>
                  )}

                  <h3 style={{ marginTop: 22 }}>Bundled firmware images</h3>
                  <p className="page-sub" style={{ marginBottom: 8 }}>
                    Images OpenFlow knows, keyed by the hash the device reports. The images themselves
                    are open-sourced as they are dumped/obtained.
                  </p>
                  {(firmware?.images || []).length === 0
                    ? <div className="empty">No firmware images catalogued.</div>
                    : firmware.images.map((im) => (
                      <div className="skp-row" key={im.file} style={{ cursor: "default" }}>
                        <span className="skp-beh">{im.side || "?"}</span>
                        <span className="skp-act" style={{ flex: 1 }}>Create {im.createFirmware} · {im.file}</span>
                        <span className="v" style={{ fontFamily: "var(--font-mono)", opacity: 0.7 }}>{im.sha256}…</span>
                      </div>
                    ))}

                  <div className="settings-links" style={{ marginTop: 16 }}>
                    <a href={`https://github.com/${REPOS.app}`} target="_blank" rel="noreferrer">OpenFlow ↗</a>
                    <a href={`https://github.com/${REPOS.companion}`} target="_blank" rel="noreferrer">Create Companion ↗</a>
                    <a href={`https://github.com/${REPOS.firmware}`} target="_blank" rel="noreferrer">Firmware ↗</a>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
