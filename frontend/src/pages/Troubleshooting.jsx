import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import BleSlots from "../components/BleSlots";

// The page the nav calls "Information". It used to show none: three action buttons and a raw
// JSON dump, with every action hardcoded to the left half.
//
// It answers two questions, in that order of prominence. "Is it healthy?" -- specifically
// whether a half that seems missing is dead or merely no longer bonded to its partner, which
// look identical from outside and need opposite repairs. Then "what do I have?", per half and
// per module, with the firmware you run set against the firmware Naya ships.
//
// Layout note: the halves use a fixed two-column grid, not the shared .grid, whose auto-fill of
// 280px tracks left two narrow cards stranded in three empty columns on a wide window.

function KV({ k, v, mono = true, title }) {
  if (v === null || v === undefined || v === "") return null;
  return (
    <div className="info-kv" title={title}>
      <span className="info-k">{k}</span>
      <span className={"info-v" + (mono ? " mono" : "")}>{v}</span>
    </div>
  );
}

// NayaFlow's own thresholds, so a battery reads the same here as in the app people came from.
function batteryTone(pct) {
  if (pct == null) return "";
  if (pct < 22) return "err";
  if (pct < 67) return "warn";
  return "ok";
}

function Battery({ pct, mv }) {
  if (pct == null) return null;
  return (
    <div className="info-kv">
      <span className="info-k">Battery</span>
      <span className="info-v">
        <span className="bat">
          <span className={"bat-fill " + batteryTone(pct)} style={{ width: `${pct}%` }} />
        </span>
        <span className="mono">{pct}%</span>
        {mv ? <span className="info-dim mono">{mv} mV</span> : null}
      </span>
    </div>
  );
}

const PAIRING = {
  paired: { tone: "ok", text: "Halves are bonded to each other" },
  "half-paired": { tone: "warn", text: "Only one half points at its partner" },
  "not-paired": { tone: "err", text: "Halves are not bonded to each other" },
  incomplete: { tone: "warn", text: "Both halves must be connected to check" },
  unknown: { tone: "warn", text: "Neither half reported a pair address" },
};

function HalfCard({ h, reference }) {
  const m = h.module;
  const behind = reference && h.firmwareVersion && h.firmwareVersion !== reference.createFirmware;
  const modBehind = reference && m?.firmwareVersion && m.firmwareVersion !== reference.moduleFirmware;
  return (
    <div className="card info-card">
      <div className="info-card-head">
        <span className={"dot " + (h.connected ? "ok" : "err")} />
        <h3>{h.description || h.side}</h3>
        <span className="pill">{h.side}</span>
      </div>
      {h.error && <div className="phase-note">{h.error}</div>}

      <div className="info-sub">Identity</div>
      <KV k="Firmware" v={h.firmwareVersion} />
      {behind && <div className="info-flag">Naya ships {reference.createFirmware}</div>}
      <KV k="Hardware ID" v={h.hardwareId} />
      <KV k="USB product id"
        v={h.pid != null ? `0x${h.pid.toString(16).toUpperCase().padStart(4, "0")}` : null}
        title="Identifies which half this is, and which firmware image it would take." />
      <KV k="Port" v={h.port} />
      <Battery pct={h.batteryPercent} mv={h.batteryMillivolts} />

      {h.ble && (
        <>
          <div className="info-sub">Bluetooth</div>
          <KV k="Name" v={h.ble.name || "(unset)"} mono={false} />
          <KV k="Address" v={h.bleAddress} />
          <KV k="Paired to" v={h.ble.pairAddress}
            title="The address this half is bonded to. On a healthy pair this is the other half's address." />
          <KV k="Dongle" v={h.ble.dongleAddress} />
          <KV k="Radio firmware" v={h.ble.firmwareVersion} />
        </>
      )}

      <div className="info-sub">Docked module</div>
      {!m ? (
        <div className="info-empty">Nothing docked on this half.</div>
      ) : (
        <>
          <KV k="Type" v={m.type} mono={false} />
          <KV k="Firmware" v={m.firmwareVersion} />
          {modBehind && <div className="info-flag">Naya ships {reference.moduleFirmware}</div>}
          <KV k="Address" v={m.address != null ? `0x${m.address.toString(16).toUpperCase()}` : null} />
          <Battery pct={m.batteryPercent} mv={m.batteryMillivolts} />
        </>
      )}
    </div>
  );
}

export default function Troubleshooting() {
  const [halves, setHalves] = useState([]);
  const [pairing, setPairing] = useState(null);
  const [recovery, setRecovery] = useState([]);
  const [sys, setSys] = useState(null);
  const [at, setAt] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [side, setSide] = useState("left");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);   // read in this session, not restored from cache
  const [now, setNow] = useState(() => Date.now());
  // Device | Connections | Troubleshooting. Device Manager's contents fold into these, so that
  // page leaves the nav (2026-09-11, owner). More tabs may come; these three are the spine.
  const [tab, setTab] = useState("device");

  // Tick so the age stays true while the page sits open, rather than freezing at whatever it
  // said on mount.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await api.statusDeep();
      setHalves(r.halves || []);
      setPairing(r.pairing || null);
      setRecovery(r.recovery || []);
      setAt(r.at ? new Date(r.at + "Z") : new Date());
      setLive(true);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, []);

  // System info is free (no USB), so it loads on mount. The device read is NOT, so the page
  // paints the last one from cache and only re-reads on a click -- the same bargain Device
  // Manager makes. Without this the page went blank every time you navigated away and back.
  useEffect(() => {
    let cancelled = false;
    api.systemInfo().then((r) => !cancelled && setSys(r)).catch(() => {});
    (async () => {
      try {
        const last = await api.statusLastDeep();
        if (cancelled || !last?.halves?.length) return;
        setHalves(last.halves);
        setPairing(last.pairing || null);
        setAt(last.at ? new Date(last.at + "Z") : null);
      } catch { /* nothing cached yet: the Read button is right there */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // Lighting controls, moved here from Device Manager. Restore is one layer-list write that
  // puts both halves back to the stored colours and animation; on/off are the plain LED
  // commands per half. All report into the output box like the diagnostics do.
  async function lighting(label, fn) {
    await run(label, fn);
  }

  async function run(label, fn) {
    setBusy(true); setOut(`${label}…`);
    try { const res = await fn(); setOut(`${label}:\n${JSON.stringify(res, null, 2)}`); }
    catch (e) { setOut(`${label} failed:\n${e.message}`); }
    finally { setBusy(false); }
  }

  // How old the reading is, shown rather than used to throw it away. Nothing here expires on a
  // clock: firmware, hardware ids and BLE addresses do not change while you look at them, and
  // blanking the page after N minutes would recreate the "it went empty" problem the cache was
  // added to fix. Battery and pairing DO drift, so the age is stated and goes amber once it is
  // old enough that a reading is worth repeating.
  const ageMs = at ? Math.max(0, now - at.getTime()) : null;
  const STALE_MS = 10 * 60 * 1000;
  const stale = ageMs != null && ageMs > STALE_MS;
  const ageText = ageMs == null ? null
    : ageMs < 60000 ? "just now"
    : ageMs < 3600000 ? `${Math.floor(ageMs / 60000)} min ago`
    : ageMs < 86400000 ? `${Math.floor(ageMs / 3600000)} h ago`
    : `${Math.floor(ageMs / 86400000)} d ago`;

  const connectedSides = halves.filter((h) => h.connected).map((h) => h.side);
  const p = pairing && PAIRING[pairing.state];

  return (
    <div className="info-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Information</h1>
          <p className="page-sub">
            What is connected, what firmware it runs, and whether the halves can see each other.
          </p>
        </div>
        <div className="board-actions-stack">
          <button className="btn primary" onClick={refresh} disabled={loading}>
            {loading ? "Reading…" : at ? "Read again" : "Read device info"}
          </button>
          <span className={"saved-note" + (stale ? " stale" : "")}>
            {at
              ? `${live ? "read" : "as of"} ${at.toLocaleTimeString()} · ${ageText}`
              : "Reads over USB. Nothing is written."}
          </span>
        </div>
      </div>

      <div className="seg info-tabs">
        {[["device", "Device"], ["connections", "Connections"], ["troubleshooting", "Troubleshooting"]].map(([id, label]) => (
          <button key={id} className={"seg-btn" + (tab === id ? " active" : "")} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      {tab === "device" && (
        <>
          {!at && !loading && (
            <div className="card info-blank">
              <h3>Nothing read yet</h3>
              <div className="setting-desc">
                Press <strong>Read device info</strong> to ask both halves who they are. It is a
                read-only USB query — nothing is written to the keyboard.
              </div>
            </div>
          )}
          {recovery.length > 0 && (
            <div className="info-banner warn">
              <div className="info-banner-title">
                Bootloader
                <span className="pill warn">
                  {recovery.length} half{recovery.length === 1 ? "" : "s"} in recovery
                </span>
              </div>
              <div className="info-banner-detail">
                {recovery.map((r) => r.port).join(", ")} — a half in MCUboot answers none of the
                normal protocol, which is why it shows here rather than above.
              </div>
              <div className="info-banner-help">
                This is not damage. Recovery boots the keyboard's normal firmware again on its own
                after a few seconds of inactivity, so a half usually leaves it without help.
              </div>
            </div>
          )}
          {stale && halves.length > 0 && (
            <div className="info-stale-note">
              This reading is {ageText}. Firmware and addresses will not have changed, but battery
              and pairing may have — read again for those.
            </div>
          )}
          {halves.filter((h) => h.side !== "dongle").length > 0 && (
            <div className="info-halves">
              {halves.filter((h) => h.side !== "dongle").map((h) => (
                <HalfCard key={h.port} h={h} reference={sys?.reference} />
              ))}
            </div>
          )}
        </>
      )}

      {tab === "connections" && (
        <>
          {pairing && (
            <div className={"info-banner " + (p ? p.tone : "")}>
              <div className="info-banner-title">
                Split link
                {p && <span className={"pill " + p.tone}>{p.text}</span>}
              </div>
              <div className="info-banner-detail">{pairing.detail}</div>
              {pairing.state !== "paired" && pairing.state !== "incomplete" && (
                <div className="info-banner-help">
                  Both halves are talking to this computer over USB, so neither is dead — they are
                  just not bonded to each other. Re-pairing is the repair here, not a firmware update.
                </div>
              )}
              {pairing.state === "incomplete" && connectedSides.length > 0 && (
                <div className="info-banner-help">
                  Only the {connectedSides.join(" and ")} half answered over USB. Connect the missing
                  half directly with its own USB-C cable and read again — each half enumerates on its
                  own, so one can be reached even when the other cannot see it.
                </div>
              )}
            </div>
          )}
          <div className="info-halves">
            <div className="card info-card">
              <div className="info-card-head"><h3>Bluetooth slots</h3></div>
              {/* Which of the five slots the keyboard sends to, and what each holds. A state of
                  the keyboard, not a preference of the app, which is why it is here. */}
              <BleSlots />
            </div>
            {halves.filter((h) => h.side === "dongle").length > 0
              ? halves.filter((h) => h.side === "dongle").map((h) => (
                  <HalfCard key={h.port} h={h} reference={sys?.reference} />
                ))
              : (
                <div className="card info-card">
                  <div className="info-card-head"><h3>Dongle</h3></div>
                  <div className="setting-desc">
                    Not on USB. When the wireless dongle is plugged in it enumerates as its own
                    serial device and appears here after a read. On firmware 3.07 it exposes no
                    keyboard interface, so it cannot bridge a wireless keyboard to this computer.
                  </div>
                </div>
              )}
          </div>
        </>
      )}

      {tab === "troubleshooting" && (
        <>
          <div className="info-halves">
            <div className="card info-card">
              <div className="info-card-head"><h3>Lighting</h3></div>
              <div className="setting-desc" style={{ marginBottom: 10 }}>
                Restore puts both halves back to the profile's stored colours and animation after
                a lighting key changed them at runtime. On and off are the plain LED commands, per
                half.
              </div>
              <div className="btn-row info-btn-wrap">
                <button className="btn primary" disabled={busy}
                  onClick={() => lighting("Restore lighting", () => api.restoreLighting("left"))}>
                  Restore lighting
                </button>
                {["left", "right"].map((sd) => (
                  <span key={sd} className="btn-row">
                    <button className="btn" disabled={busy || (at != null && !connectedSides.includes(sd))}
                      onClick={() => lighting(`LEDs on (${sd})`, () => api.led(sd, "on"))}>
                      LEDs on ({sd})
                    </button>
                    <button className="btn" disabled={busy || (at != null && !connectedSides.includes(sd))}
                      onClick={() => lighting(`LEDs off (${sd})`, () => api.led(sd, "off"))}>
                      LEDs off ({sd})
                    </button>
                  </span>
                ))}
              </div>
            </div>
            <div className="card info-card">
              <div className="info-card-head"><h3>Diagnostics</h3></div>
              <div className="setting-desc" style={{ marginBottom: 10 }}>
                Run against a chosen half. These read the device; none of them change a binding.
              </div>
              <div className="seg">
                {["left", "right", "dongle"].map((sd) => (
                  <button key={sd}
                    className={"seg-btn" + (side === sd ? " active" : "")}
                    disabled={at != null && !connectedSides.includes(sd)}
                    title={at != null && !connectedSides.includes(sd) ? "Not connected" : undefined}
                    onClick={() => setSide(sd)}>
                    {sd}
                  </button>
                ))}
              </div>
              <div className="btn-row info-btn-wrap">
                <button className="btn" disabled={busy} onClick={() => run("Diagnostics report", api.diagnostics)}>
                  Generate report
                </button>
                <button className="btn" disabled={busy} onClick={() => run("Dump settings", () => api.dumpSettings(side))}>
                  Dump settings
                </button>
                <button className="btn" disabled={busy}
                  onClick={() => run("SPI flash self-test", () => api.sendCommand("repair_flash", [], { side }))}>
                  Test SPI flash
                </button>
              </div>
              <div className="info-sub">Recovery</div>
              <div className="setting-desc" style={{ marginBottom: 10 }}>
                Clears Bluetooth bonds on the <strong>{side}</strong> half. If the halves are bonded
                to each other they will need re-pairing afterwards.
              </div>
              <button className="btn danger" disabled={busy}
                onClick={() => {
                  if (confirm(`Clear all Bluetooth bonds on the ${side} half?`)) {
                    run("Clear BLE devices", () => api.sendCommand("clear_ble_devices", [], { side, force: true }));
                  }
                }}>
                Clear BLE devices ({side})
              </button>
            </div>
            <div className="card info-card">
              <div className="info-card-head"><h3>Software</h3></div>
              <KV k="OpenFlow" v={sys?.backendVersion} />
              <KV k="Operating system" v={sys ? `${sys.os} ${sys.osVersion}` : null} mono={false} />
              <KV k="Architecture" v={sys?.arch} />
              <KV k="Python" v={sys?.python} />
              {sys?.reference && (
                <>
                  <div className="info-sub">Firmware Naya ships</div>
                  <KV k="Create" v={sys.reference.createFirmware} />
                  <KV k="Module" v={sys.reference.moduleFirmware} />
                  <KV k="Source" v={sys.reference.source} mono={false} />
                </>
              )}
            </div>
          </div>
          {out && (
            <div className="card">
              <div className="info-card-head">
                <h3>Output</h3>
                <button className="btn info-head-btn" onClick={() => setOut("")}>Clear</button>
              </div>
              <pre className="info-out">{out}</pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}
