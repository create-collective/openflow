import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { confirmDialog } from "../lib/dialogs";
import { applyInterfaceScaling } from "../lib/scaling";
import { pickFile, downloadJSON, safeName } from "../lib/files";
import FirmwareLibrary from "../components/FirmwareLibrary";
import FirmwareUpdate from "../components/FirmwareUpdate";
import ModuleFirmwareUpdate from "../components/ModuleFirmwareUpdate";
import SettingField from "../components/SettingField";
import SettingRow from "../components/ui/SettingRow";
import useRunLog from "../lib/useRunLog";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import { KVRow } from "../components/ui/KV";
import Notice from "../components/ui/Notice";
import Tabs from "../components/ui/Tabs";
import { useDeviceStream } from "../lib/deviceStream";
import { setShowAllKeyboards, useShowAllKeyboards } from "../lib/showAllKeyboards";
import { THEME_PREFERENCES, setThemePreference, useThemePreference } from "../lib/theme";
// Placeholder repo paths — update to the real OpenFlow / firmware repos once public.
import { ORG, REPOS, checkRelease } from "../lib/updates";

// The rail, as the storyboard draws it: an icon per section (Tabler Icons, MIT, Pawel Kuna:
// settings, device-desktop, database, tool, file-text, info-circle).
const GLYPH = {
  behavior: <><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37c1 .608 2.296.07 2.572-1.065z" /><path d="M9 12a3 3 0 1 0 6 0a3 3 0 0 0-6 0" /></>,
  interface: <><rect x="3" y="4" width="18" height="12" rx="1" /><path d="M7 20h10M9 16v4M15 16v4" /></>,
  backup: <><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6a8 3 0 0 0 16 0V6" /><path d="M4 12v6a8 3 0 0 0 16 0v-6" /></>,
  troubleshooting: <path d="M7 10h3v-3l-3.5-3.5a6 6 0 0 1 8 8l6 6a2 2 0 0 1-3 3l-6-6a6 6 0 0 1-8-8l3.5 3.5" />,
  logging: <><path d="M14 3v4a1 1 0 0 0 1 1h4" /><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" /><path d="M9 9h1M9 13h6M9 17h6" /></>,
  // firmware: a chip, as the board's own software; about: the info circle.
  firmware: <><rect x="7" y="7" width="10" height="10" rx="1.5" /><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4" /></>,
  about: <><circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v4h1" /></>,
};
function RailGlyph({ id }) {
  return (
    <svg className="settings-glyph" viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {GLYPH[id]}
    </svg>
  );
}

// Each section's page head: what it is, its scope as a badge, one line on what it covers.
const SECTIONS = [
  { id: "behavior", label: "Behavior", badge: "device", sub: "How keys resolve on the keyboard. Flashed to the device." },
  { id: "interface", label: "Interface", badge: "app only", sub: "How OpenFlow looks and behaves on this computer." },
  { id: "backup", label: "Backup", badge: "app only", sub: "Snapshots of your data, and NayaFlow imports." },
  { id: "troubleshooting", label: "Troubleshooting", badge: "destructive", sub: "Restart and recover your keyboard." },
  { id: "logging", label: "Logging", sub: "Diagnostics, and everything exchanged with the keyboard." },
  // Firmware is the keyboard's own software and nothing else: what each half runs, what can be
  // written to it, and the library of images it could be written from. Everything about
  // OpenFlow itself -- its version, its update checks, where to find it -- moved to About, so
  // this tab is only ever about the board in front of you (owner, 2026-09-21).
  { id: "firmware", label: "Firmware", badge: "device", sub: "What your keyboard runs, and what you can put on it." },
  { id: "about", label: "About", sub: "OpenFlow's own version, update checks and links." },
];
const TABS = SECTIONS.map((s) => ({ id: s.id, label: s.label, icon: <RailGlyph id={s.id} /> }));

// The storyboard shows Behavior as two cards, key behaviour and power on the left and LED
// behaviour on the right, with OneKey Timing under the latter. The backend has the LED
// settings in the Behavior group; they are split off here, by id, for the layout only.
function splitLed(groups) {
  const out = [];
  for (const g of groups) {
    const led = g.fields.filter((f) => f.id.startsWith("led_"));
    if (led.length && led.length < g.fields.length) {
      // The group description is already the section head, so neither card repeats it.
      out.push({ ...g, group: "Key behavior & power", desc: undefined, fields: g.fields.filter((f) => !f.id.startsWith("led_")) });
      out.push({ ...g, group: "LED behavior", desc: undefined, fields: led });
    } else out.push(g);
  }
  return out;
}

// The groups as cards, one under another (the storyboard tiles them in two columns; the
// owner preferred the tiles stacked).
function SettingsGroups({ groups, onChange }) {
  if (!groups.length) return null;
  return (
    <div className="settings-cards">
      {groups.map((g) => (
        <Card key={g.group} className="settings-card" title={g.group}>
          {g.desc && <p className="settings-card-desc">{g.desc}</p>}
          {g.fields.map((f) => <SettingField key={f.id} f={f} onChange={onChange} />)}
        </Card>
      ))}
    </div>
  );
}

function DeviceGate({ connected, children }) {
  if (connected) return children;
  return <Notice>Connect a Naya Create over USB to use this. These actions run on the device.</Notice>;
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
  // The repair runs from a plan, never blind: the backend's own answer decides, and the reason
  // it cannot run is the button's title. It was a hardcoded disabled button, so a session that
  // unlocked the repair (OPENFLOW_ENABLE_PAIRING_REPAIR) still had no way to start it.
  const pairingBlocker = !pairPlan ? "Plan the repair first"
    : pairPlan.refused ? `Refused: ${pairPlan.refused}`
      : !pairPlan.enabled ? "Locked: OpenFlow was not started with pairing repair unlocked"
        : pairPlan.opsDisabled?.length ? `Locked: these steps are not unlocked: ${pairPlan.opsDisabled.join(", ")}`
          : null;
  const canRunPairing = !!pairPlan?.armToken && !pairingBlocker;
  const { out, busy, run } = useRunLog();
  const [err, setErr] = useState(null);
  const { data: stream } = useDeviceStream();

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
    // The firmware tab does NOT read the keyboard on open. It paints from the poll's live
    // snapshot instead (see liveHalves below), so plugging a half in while the tab is open is
    // noticed. The catalogue is a file on disk and never changes under us.
    if (tab === "firmware") api.firmwareCatalog().then(setFirmware).catch(() => {});
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

  // Troubleshooting's buttons gate on the reading IT took when the tab opened; the firmware tab
  // gates on the live poll instead.
  //
  // It used to share that one-shot fetch, which ran only when the tab changed. Open the tab,
  // then plug the keyboard in, and nothing refetched: the halves stayed absent and "Update
  // firmware" stayed disabled saying "Connect the keyboard first" with the keyboard connected
  // (owner, 2026-09-21). The device stream is already open for the whole app and says so within
  // a tick, so the tab is live and costs no read of its own.
  const connected = status.some((h) => h.connected);
  const liveHalves = (stream?.status?.halves || []).filter((h) => h.connected);
  const firmwareConnected = liveHalves.length > 0;

  // One opt-in release check (lib/updates), reused for OpenFlow and Create Companion -- no
  // forced updater.
  const checkUpdate = () => checkRelease(REPOS.app, sys?.backendVersion, setUpdate);
  const checkCompanion = () => checkRelease(REPOS.companion, null, setCompanion);

  // Route by SCOPE, not by name. This was `group !== "Interface"` vs `=== "Interface"`, so
  // "OneKey Timing" landed on the Behavior tab by accident and any group added to the backend
  // later would silently land there too.
  const behaviorGroups = splitLed(settings?.groups.filter((g) => g.scope === "device") || []);
  const interfaceGroups = settings?.groups.filter((g) => g.scope !== "device") || [];
  // The theme lives on this machine (localStorage, applied before first paint by index.html),
  // not in the backend's settings: it is a property of the screen in front of you, like the
  // window size, and it must be right before the backend has answered.
  const themePref = useThemePreference();
  const showAllKb = useShowAllKeyboards();
  const appearanceGroups = [{
    group: "Appearance",
    desc: "How OpenFlow looks on this computer.",
    fields: [{
      id: "theme", label: "Theme", kind: "select", options: THEME_PREFERENCES,
      value: themePref, default: "system", provenance: "app",
      desc: "System follows the operating system's light or dark setting.",
    }, {
      // A troubleshooting aid for working on the multi-keyboard handling, not something a
      // user has a reason to turn on: normally the app simply shows what is connected, and
      // an unplugged keyboard stops being drawn as soon as another one is still there.
      id: "showAllKeyboards", label: "Keep disconnected keyboards on screen", kind: "toggle",
      value: showAllKb, default: false, provenance: "app",
      desc: "Off: only keyboards that are connected are shown, and the keyboard picker "
            + "appears only when there is genuinely more than one. On: every keyboard seen "
            + "since launch stays visible, which is for troubleshooting the multi-keyboard "
            + "handling itself.",
    }],
  }];

  const section = SECTIONS.find((s) => s.id === tab);

  return (
    <div className="settings-page">
      {err && <Notice tone="err" className="settings-err" onDismiss={() => setErr(null)}>{err}</Notice>}

      <div className="settings-layout">
        <div className="settings-rail">
          <h1 className="settings-rail-title">Settings</h1>
          <Tabs variant="vertical" ariaLabel="Settings sections" items={TABS} value={tab} onChange={setTab} />
        </div>

        <div className="settings-content">
          <div className="settings-head">
            <h2 className="settings-title">
              {section.label}
              {section.badge && <Badge className="ui-badge-plain">{section.badge}</Badge>}
            </h2>
            <p className="settings-sub">{section.sub}</p>
          </div>
          {!settings ? <div className="empty">Loading…</div> : (
            <>
              {tab === "behavior" && <SettingsGroups groups={behaviorGroups} onChange={setSetting} />}
              {tab === "interface" && (
                <SettingsGroups groups={[...appearanceGroups, ...interfaceGroups]}
                  onChange={(id, v) => (id === "theme" ? setThemePreference(v)
                    : id === "showAllKeyboards" ? setShowAllKeyboards(v)
                      : setSetting(id, v))} />
              )}

              {tab === "backup" && (
                <Card className="settings-pane wide" title="Local backups">
                  <p className="settings-card-desc">OpenFlow auto-backs up your data every 30 minutes. Restore any snapshot below.</p>
                  <div className="btn-row" style={{ marginBottom: 8 }}>
                    <Button variant="primary" disabled={busy} onClick={() => run("Backup now", async () => { const r = await api.createBackup(); setBackups(await api.backups()); return r; })}>Backup now</Button>
                    {backups.dir && (
                      <Button disabled={busy} onClick={() => run("Open backup folder", api.openBackupFolder)}>Open backup folder</Button>
                    )}
                    <Button disabled={busy} onClick={async () => {
                      const f = await pickFile(".db,.zip");
                      if (!f) return;
                      if (!(await confirmDialog({ title: "Import this backup as your current data?", message: "Your current data is snapshotted first.", confirmLabel: "Import" }))) return;
                      run("Import backup", async () => { const r = await api.importBackupFile(f); setBackups(await api.backups()); return r; });
                    }}>Import backup file…</Button>
                    <Button disabled={busy} onClick={async () => {
                      const f = await pickFile(".db,.zip");
                      if (!f) return;
                      run("Convert to JSON", async () => {
                        const r = await api.convertDbToJson(f);
                        for (const p of r.profiles) {
                          downloadJSON(`${safeName(p.profile?.name || "profile")}.json`, p);
                        }
                        return { converted: r.profiles.length, saved: r.profiles.map((p) => p.profile?.name) };
                      });
                    }}>Convert database to JSON…</Button>
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
                      <Button disabled={busy} onClick={async () => { if (await confirmDialog({ title: "Restore this backup?", message: "Current data is snapshotted first.", confirmLabel: "Restore" })) run("Restore", () => api.restoreBackup(b.name)); }}>Restore</Button>
                    </div>
                  ))}
                  {out && <pre className="settings-out">{out}</pre>}
                </Card>
              )}

              {tab === "troubleshooting" && (
                <Card className="settings-pane" title="Device data">
                  <p className="settings-card-desc">
                    Actions that erase device data, kept apart from the safe, read-only diagnostics.
                    Those (lighting restore, SPI self-test, diagnostics report, dump settings) live on
                    the <strong>Information &rsaquo; Troubleshooting</strong> tab.
                  </p>
                  <DeviceGate connected={connected}>
                    <SettingRow label="Clear BLE Devices" desc="Forces the Create to forget all Bluetooth connections."
                      control={<Button variant="danger" disabled={busy} onClick={async () => { if (await confirmDialog({ title: "Clear all Bluetooth bonds?", message: "If the halves are bonded to each other they will need re-pairing.", confirmLabel: "Clear", tone: "danger" })) run("Clear BLE", () => api.sendCommand("clear_ble_devices", [], { side: "left", force: true })); }}>Clear</Button>} />
                  </DeviceGate>

                  <h3 className="settings-section">Recovery procedures</h3>
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
                          <SettingRow key={op.id} label={op.label}
                            badge={<Badge size="xs" tone={op.danger === "destructive" ? "warn" : "neutral"}>{op.danger}</Badge>}
                            control={
                              <Button variant={op.danger === "destructive" ? "danger" : "secondary"}
                                disabled={!op.enabled || busy || !connected}
                                title={!op.enabled ? `Wired, enabled after testing on a ${op.needs}` : op.confirm}
                                onClick={async () => { if (await confirmDialog({ title: `Run ${op.label}?`, message: op.confirm, confirmLabel: "Run", tone: op.danger === "destructive" ? "danger" : "default" })) run(op.label, () => api.runRecoveryOp(op.id)); }}>
                                {op.enabled ? "Run" : "Disabled"}
                              </Button>
                            }
                            desc={<>
                              {op.desc}{!op.enabled && <> — <em>wired, enabled after testing on a {op.needs}.</em></>}
                              <span className="settings-command">{op.command}</span>
                            </>} />
                        ))}
                      </div>
                    );
                  })}
                  <h3 className="settings-section">Guided split-link repair</h3>
                  <p className="page-sub" style={{ marginBottom: 12 }}>
                    NayaFlow's pairing operation as one reviewed sequence: both halves' addresses are
                    stored <strong>before</strong> anything is cleared, each half is pointed at the
                    other, the old links and bonds are dropped, both halves restart, and the link is
                    verified. Planning only reads. Running is <strong>locked</strong> unless OpenFlow
                    was started with pairing repair unlocked, and it forgets every Bluetooth host on
                    both halves.
                  </p>
                  <SettingRow label="Plan the repair"
                    control={<>
                      <Button disabled={busy || !connected}
                        onClick={() => run("Pairing repair plan", () => api.pairingRepairPlan().then((p) => { setPairPlan(p); return p; }))}>Plan</Button>
                      <Button disabled={busy || !connected}
                        onClick={() => run("Pairing verify", () => api.pairingRepairVerify())}>Verify link</Button>
                      <Button variant="danger" disabled={!canRunPairing || busy || !connected}
                        title={pairingBlocker || "Run the steps above, in order"}
                        onClick={async () => {
                          if (await confirmDialog({
                            title: "Run the split-link repair?",
                            message: "Both halves are pointed at each other, every Bluetooth pairing on both halves is forgotten (your computers too), and both halves restart. Keep both halves plugged in until it finishes.",
                            confirmLabel: "Run repair", tone: "danger" })) {
                            // A plan is spent once run: the halves restart, so another run needs a fresh one.
                            run("Pairing repair", () => api.pairingRepair(pairPlan.armToken, true)
                              .finally(() => setPairPlan(null)));
                          }
                        }}>Run</Button>
                    </>}
                    desc={<>
                      {!pairPlan && <>Reads both halves and lists every step with its exact command. Nothing is sent.</>}
                      {pairPlan?.refused && <>Refused: {pairPlan.refused}</>}
                      {pairPlan?.steps && (
                        <ol style={{ margin: "6px 0 0 18px", padding: 0 }}>
                          {pairPlan.steps.map((s, i) => (
                            <li key={i} style={{ marginBottom: 2 }}>
                              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{s.name}</span>
                              {s.side ? ` (${s.side})` : ""} — {s.detail}
                              {s.command && <span className="settings-command">{s.command}</span>}
                            </li>
                          ))}
                        </ol>
                      )}
                      {pairPlan?.record && (
                        <span className="devlog-detail" style={{ display: "block", opacity: 0.6, fontFamily: "var(--font-mono)", fontSize: 11, marginTop: 6 }}>
                          would store: left {pairPlan.record.left.bleAddress} (paired to {pairPlan.record.left.pairAddress || "nothing"}), right {pairPlan.record.right.bleAddress} (paired to {pairPlan.record.right.pairAddress || "nothing"}) · arm {pairPlan.armToken}
                        </span>
                      )}
                    </>} />
                  {out && <pre className="settings-out">{out}</pre>}
                </Card>
              )}

              {tab === "logging" && (
                <Card className="settings-pane wider" title="Logging & diagnostics">
                  <SettingRow label="Diagnostics Report" desc="Collects system + device info to help debug issues."
                    control={<Button disabled={busy} onClick={() => run("Diagnostics", api.diagnostics)}>Generate</Button>} />
                  <SettingRow bare className="settings-log-head" label="Device I/O log"
                    control={<>
                      <Button disabled={busy} onClick={() => api.deviceLog().then((r) => { setDevlog(r.entries || []); setLogmeta(r); })}>Refresh</Button>
                      <Button disabled={busy} onClick={() => { api.clearDeviceLog().then(() => setDevlog([])); }}>Clear</Button>
                      {logmeta.dir && <Button disabled={busy} onClick={() => api.openLogsFolder()}>Open log folder</Button>}
                    </>}
                    desc={<>
                      Every command, text query and raw frame exchanged with a connected keyboard, newest last.
                      Device bytes only. Also written to a daily file under the log folder{logmeta.retentionDays ? `, kept ${logmeta.retentionDays} days` : ""}.
                      This is where a "flash failed" that actually landed shows what really happened.
                    </>} />
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
                </Card>
              )}

              {tab === "firmware" && (
                <Card className="settings-pane" title="Device firmware">

                  {liveHalves.map((h) => (
                    <div key={h.port}>
                      <KVRow k={`${h.description} firmware`} v={h.firmwareVersion || "—"} />
                      {h.module?.firmwareVersion && <KVRow k={`${h.module.type} module firmware`} v={h.module.firmwareVersion} />}
                    </div>
                  ))}
                  {!firmwareConnected && <p className="page-sub">Connect the keyboard to read device firmware versions.</p>}
                  {firmware?.reference && (
                    <KVRow k="Naya ships (reference)" v={`Create ${firmware.reference.createFirmware} · module ${firmware.reference.moduleFirmware}`} />
                  )}
                  {/* The supervised procedure: back up, flash one half at a time, verify against
                      the backup, keep the log (SCRUM-104). The per-image buttons in the library
                      below stay inert -- that list is the catalogue, and a flash is not a thing
                      to start from a row in a reference table.

                      Keyboard and module are two buttons because they are two procedures: one
                      swaps an MCUboot slot and can be rolled back, the other writes a filesystem
                      and cannot, and they want opposite setups -- keyboard firmware with no
                      module docked on either half (SCRUM-114), module firmware with only the left
                      half connected and one module in its bay. */}
                  <div className="btn-row fw-actions">
                    <FirmwareUpdate
                      connected={firmwareConnected}
                      dockedModules={liveHalves.filter((h) => h.module).map((h) => ({
                        side: h.side, type: h.module.type,
                      }))}
                    />
                    <ModuleFirmwareUpdate connected={firmwareConnected} />
                    {/* Its own button, not an option inside the dialog above: it exists for the
                        module that cannot pass that dialog's identification check (owner). */}
                    <ModuleFirmwareUpdate connected={firmwareConnected} force />
                  </div>

                  <h3 className="settings-section tight">Firmware library</h3>
                  {!firmware?.images?.length
                    ? <div className="empty">No firmware images catalogued.</div>
                    : <FirmwareLibrary images={firmware.images} />}

                </Card>
              )}

              {tab === "about" && (
                <Card className="settings-pane" title="About OpenFlow">
                  <KVRow k="OpenFlow" v={sys?.backendVersion} />
                  <KVRow k="OS" v={sys ? `${sys.os} ${sys.arch}` : null} />
                  <div className="btn-row" style={{ margin: "10px 0" }}>
                    <Button onClick={checkUpdate}>Check OpenFlow for updates</Button>
                    <Button onClick={checkCompanion}>Check Create Companion</Button>
                  </div>
                  {update?.checking && <div className="page-sub">Checking OpenFlow…</div>}
                  {update?.error && <Notice tone="err">OpenFlow: {update.error}</Notice>}
                  {update?.latest && <KVRow k="OpenFlow latest" v={`${update.latest}${update.ahead ? " (update available)" : " (up to date)"}`} />}
                  {companion?.checking && <div className="page-sub">Checking Create Companion…</div>}
                  {companion?.error && <Notice tone="err">Create Companion: {companion.error}</Notice>}
                  {companion?.latest && <KVRow k="Create Companion latest" v={companion.latest} />}
                  <p className="page-sub" style={{ marginTop: 4 }}>
                    Opt-in checks against GitHub Releases. OpenFlow has no forced updater. These
                    are checks on OpenFlow itself — your keyboard&rsquo;s own firmware lives on
                    the Firmware tab.
                  </p>

                  <h3 className="settings-section tight">Source</h3>
                  <div className="settings-links">
                    <a href={`https://github.com/${ORG}`} target="_blank" rel="noreferrer">create-collective ↗</a>
                    <a href={`https://github.com/${REPOS.app}`} target="_blank" rel="noreferrer">OpenFlow ↗</a>
                    <a href={`https://github.com/${REPOS.companion}`} target="_blank" rel="noreferrer">Create Companion ↗</a>
                    {/* "Legacy": Naya's own firmware, preserved. Community open-source firmware
                        gets its own link here when it exists. */}
                    <a href={`https://github.com/${REPOS.firmware}`} target="_blank" rel="noreferrer">Legacy Firmware ↗</a>
                  </div>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
