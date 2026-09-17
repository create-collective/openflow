import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { applyInterfaceScaling } from "../lib/scaling";
import { pickFile, downloadJSON, safeName } from "../lib/files";
import SettingField from "../components/SettingField";
import { THEME_PREFERENCES, setThemePreference, useThemePreference } from "../lib/theme";
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
  const [devlog, setDevlog] = useState([]);
  const [logmeta, setLogmeta] = useState({});
  const [recovery, setRecovery] = useState([]);
  const [pairPlan, setPairPlan] = useState(null);
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
    if (tab === "logging") api.deviceLog().then((r) => { setDevlog(r.entries || []); setLogmeta(r); }).catch(() => {});
    // Troubleshooting gates its buttons on `connected`, which only the Software tab used to
    // fetch, so with a keyboard plugged in every device button here stayed disabled.
    if (tab === "troubleshooting") { api.recoveryOps().then((r) => setRecovery(r.ops || [])).catch(() => {}); api.status().then((r) => setStatus(r.halves || [])).catch(() => {}); }
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
  // The theme lives on this machine (localStorage, applied before first paint by index.html),
  // not in the backend's settings: it is a property of the screen in front of you, like the
  // window size, and it must be right before the backend has answered.
  const themePref = useThemePreference();
  const appearanceGroups = [{
    group: "Appearance",
    desc: "How OpenFlow looks on this computer.",
    fields: [{
      id: "theme", label: "Theme", kind: "select", options: THEME_PREFERENCES,
      value: themePref, default: "system", provenance: "app",
      desc: "System follows the operating system's light or dark setting.",
    }],
  }];

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
              {tab === "interface" && (
                <>
                  <SettingsGroups groups={appearanceGroups} onChange={(_id, v) => setThemePreference(v)} />
                  <SettingsGroups groups={interfaceGroups} onChange={setSetting} />
                </>
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
                  <h3>Troubleshooting <span className="pill danger">destructive</span></h3>
                  <p className="page-sub" style={{ marginBottom: 12 }}>
                    Actions that erase device data, kept apart from the safe, read-only diagnostics.
                    Those (lighting restore, SPI self-test, diagnostics report, dump settings) live on
                    the <strong>Information &rsaquo; Troubleshooting</strong> tab.
                  </p>
                  <DeviceGate connected={connected}>
                    <div className="setting">
                      <div className="setting-head"><strong>Clear BLE Devices</strong>
                        <button className="btn danger" disabled={busy} onClick={() => { if (confirm("Clear all Bluetooth bonds? If the halves are bonded to each other they will need re-pairing.")) run("Clear BLE", () => api.sendCommand("clear_ble_devices", [], { side: "left", force: true })); }}>Clear</button></div>
                      <div className="setting-desc">Forces the Create to forget all Bluetooth connections.</div>
                    </div>
                  </DeviceGate>

                  <h3 style={{ marginTop: 26 }}>Recovery procedures</h3>
                  <p className="page-sub" style={{ marginBottom: 12 }}>
                    Device-recovery procedures recovered from the vendor software. Each is wired and
                    its exact command is pinned by tests, but they stay <strong>disabled</strong> until
                    each is verified on a spare/donor unit — a mistaken one can leave a keyboard worse
                    off. Every one runs only behind a confirmation.
                  </p>
                  {["reset", "recovery", "destructive"].map((danger) => {
                    const ops = recovery.filter((o) => o.danger === danger);
                    if (!ops.length) return null;
                    const heading = { reset: "Resets", recovery: "Recovery", destructive: "Destructive" }[danger];
                    return (
                      <div key={danger} style={{ marginBottom: 14 }}>
                        <div className="info-sub">{heading}</div>
                        {ops.map((op) => (
                          <div className="setting" key={op.id}>
                            <div className="setting-head">
                              <strong>{op.label}</strong>
                              <span className={"gesture-badge prov-" + (op.danger === "destructive" ? "experimental" : "app")}>{op.danger}</span>
                              <div className="setting-ctl">
                                <button className={"btn" + (op.danger === "destructive" ? " danger" : "")}
                                  disabled={!op.enabled || busy || !connected}
                                  title={!op.enabled ? `Wired, enabled after testing on a ${op.needs}` : op.confirm}
                                  onClick={() => { if (confirm(op.confirm)) run(op.label, () => api.runRecoveryOp(op.id)); }}>
                                  {op.enabled ? "Run" : "Disabled"}
                                </button>
                              </div>
                            </div>
                            <div className="setting-desc">
                              {op.desc}{!op.enabled && <> — <em>wired, enabled after testing on a {op.needs}.</em></>}
                              <span className="devlog-detail" style={{ display: "block", opacity: 0.5, fontFamily: "var(--font-mono)", fontSize: 11 }}>{op.command}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                  <h3 style={{ marginTop: 26 }}>Guided split-link repair</h3>
                  <p className="page-sub" style={{ marginBottom: 12 }}>
                    NayaFlow's pairing operation as one reviewed sequence: both halves' addresses are
                    stored <strong>before</strong> anything is cleared, each half is pointed at the
                    other, the old links and bonds are dropped, both halves restart, and the link is
                    verified. Planning only reads. Running is wired but <strong>disabled</strong> until
                    it is watched on a spare pair, and it forgets every Bluetooth host on both halves.
                  </p>
                  <div className="setting">
                    <div className="setting-head">
                      <strong>Plan the repair</strong>
                      <div className="setting-ctl">
                        <button className="btn" disabled={busy || !connected}
                          onClick={() => run("Pairing repair plan", () => api.pairingRepairPlan().then((p) => { setPairPlan(p); return p; }))}>Plan</button>
                        <button className="btn" disabled={busy || !connected} style={{ marginLeft: 6 }}
                          onClick={() => run("Pairing verify", () => api.pairingRepairVerify())}>Verify link</button>
                        <button className="btn danger" disabled title="Wired, enabled after testing on a spare pair" style={{ marginLeft: 6 }}>Run (disabled)</button>
                      </div>
                    </div>
                    <div className="setting-desc">
                      {!pairPlan && <>Reads both halves and lists every step with its exact command. Nothing is sent.</>}
                      {pairPlan?.refused && <>Refused: {pairPlan.refused}</>}
                      {pairPlan?.steps && (
                        <ol style={{ margin: "6px 0 0 18px", padding: 0 }}>
                          {pairPlan.steps.map((s, i) => (
                            <li key={i} style={{ marginBottom: 2 }}>
                              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{s.name}</span>
                              {s.side ? ` (${s.side})` : ""} — {s.detail}
                              {s.command && <span className="devlog-detail" style={{ display: "block", opacity: 0.5, fontFamily: "var(--font-mono)", fontSize: 11 }}>{s.command}</span>}
                            </li>
                          ))}
                        </ol>
                      )}
                      {pairPlan?.record && (
                        <span className="devlog-detail" style={{ display: "block", opacity: 0.6, fontFamily: "var(--font-mono)", fontSize: 11, marginTop: 6 }}>
                          would store: left {pairPlan.record.left.bleAddress} (paired to {pairPlan.record.left.pairAddress || "nothing"}), right {pairPlan.record.right.bleAddress} (paired to {pairPlan.record.right.pairAddress || "nothing"}) · arm {pairPlan.armToken}
                        </span>
                      )}
                    </div>
                  </div>
                  {out && <pre className="settings-out">{out}</pre>}
                </div>
              )}

              {tab === "logging" && (
                <div style={{ maxWidth: 860 }}>
                  <h3>Logging &amp; Diagnostics</h3>
                  <div className="setting">
                    <div className="setting-head"><strong>Diagnostics Report</strong>
                      <button className="btn" disabled={busy} onClick={() => run("Diagnostics", api.diagnostics)}>Generate</button></div>
                    <div className="setting-desc">Collects system + device info to help debug issues.</div>
                  </div>
                  <div className="setting-head" style={{ marginTop: 18 }}>
                    <strong>Device I/O log</strong>
                    <div className="setting-ctl">
                      <button className="btn" disabled={busy} onClick={() => api.deviceLog().then((r) => { setDevlog(r.entries || []); setLogmeta(r); })}>Refresh</button>
                      <button className="btn" disabled={busy} onClick={() => { api.clearDeviceLog().then(() => setDevlog([])); }}>Clear</button>
                      {logmeta.dir && <button className="btn" disabled={busy} onClick={() => api.openLogsFolder()}>Open log folder</button>}
                    </div>
                  </div>
                  <div className="setting-desc" style={{ marginBottom: 8 }}>
                    Every command, text query and raw frame exchanged with a connected keyboard, newest last.
                    Device bytes only. Also written to a daily file under the log folder{logmeta.retentionDays ? `, kept ${logmeta.retentionDays} days` : ""}.
                    This is where a "flash failed" that actually landed shows what really happened.
                  </div>
                  {devlog.length === 0
                    ? <div className="empty">No device I/O recorded yet. Read or flash the keyboard, then Refresh.</div>
                    : (
                      <div className="devlog">
                        {devlog.slice().reverse().map((e) => (
                          <div key={e.seq} className={"devlog-row" + (e.ok ? "" : " devlog-err")}>
                            <span className="devlog-at">{e.at}</span>
                            <span className="devlog-kind">{e.kind}</span>
                            <span className="devlog-port">{e.port}</span>
                            <span className="devlog-detail">{e.detail}</span>
                            <span className="devlog-ms">{e.ms}ms</span>
                          </div>
                        ))}
                      </div>
                    )}
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

                  <h3 style={{ marginTop: 22 }}>Firmware library</h3>
                  <p className="page-sub" style={{ marginBottom: 10 }}>
                    Every firmware image OpenFlow has classified, by what it targets and which
                    NayaFlow release bundled it — so a specific version can be picked for an
                    up/downgrade. Flashing is wired but <strong>disabled</strong> until it is tested
                    on a donor unit. Images are open-sourced as they are dumped/obtained.
                  </p>
                  {(() => {
                    const imgs = firmware?.images || [];
                    if (!imgs.length) return <div className="empty">No firmware images catalogued.</div>;
                    // One group per distinct firmware: its version number when a NayaFlow release
                    // declared one, else the release span that shipped it (the catalogue's
                    // versionLabel). Keyboard first, newest release first.
                    const label = (im) => im.versionLabel || im.version || "(unknown version)";
                    const key = (im) => `${im.target}|${label(im)}`;
                    const groups = {};
                    for (const im of imgs) (groups[key(im)] ||= []).push(im);
                    const order = Object.keys(groups).sort((a, b) => {
                      const A = groups[a][0], B = groups[b][0];
                      return (A.target === "module") - (B.target === "module")
                        || (B.releaseOrder ?? -1) - (A.releaseOrder ?? -1)
                        || a.localeCompare(b);
                    });
                    const ver = (tag) => String(tag || "").replace(/^v/, "");
                    const shippedIn = (im) => {
                      const b = im.bundles || [];
                      if (!b.length) return im.bundle;
                      if (b.length === 1) return `NayaFlow ${ver(b[0])}`;
                      return `NayaFlow ${ver(b[0])} to ${ver(b[b.length - 1])}, ${b.length} releases`;
                    };
                    return order.map((g) => {
                      const ims = groups[g];
                      const first = ims[0];
                      const declared = first.versionConfidence === "declared";
                      const kind = first.target === "module" ? "Module" : "Keyboard";
                      const title = declared ? `${kind} firmware ${label(first)}` : `${kind} firmware shipped in ${label(first)}`;
                      const sub = declared ? shippedIn(first) : "no release declared a version number";
                      return (
                        <div key={g} style={{ marginBottom: 14 }}>
                          <div className="info-sub">{title} <span style={{ opacity: 0.5, fontWeight: 400 }}>· {sub}</span></div>
                          {ims.map((im) => (
                            <div className="skp-row" key={`${im.file}-${im.sha256}`} style={{ cursor: "default" }} title={im.note || ""}>
                              <span className="skp-beh">{im.component || "?"}{im.generation ? ` · gen ${im.generation}` : ""}</span>
                              <span className="skp-act" style={{ flex: 1 }}>{im.file}{im.container ? ` in ${im.container}` : ""}</span>
                              <span className="v" style={{ fontFamily: "var(--font-mono)", opacity: 0.6 }}>{im.sha256 ? im.sha256 + "…" : "encrypted"}</span>
                              <button className="btn" disabled title={im.flashable ? "Wired, enabled after testing on a donor unit" : (im.withheldBecause || []).join("; ") || "Not a flashable image"} style={{ marginLeft: 8 }}>
                                {im.flashable ? "Flash (disabled)" : "—"}
                              </button>
                            </div>
                          ))}
                        </div>
                      );
                    });
                  })()}

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
