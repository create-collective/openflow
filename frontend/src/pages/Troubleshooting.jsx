import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import BleSlots from "../components/BleSlots";
import useRunLog from "../lib/useRunLog";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Disclosure from "../components/ui/Disclosure";
import { KVRow } from "../components/ui/KV";
import Notice from "../components/ui/Notice";
import SettingRow from "../components/ui/SettingRow";
import Tabs from "../components/ui/Tabs";

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

// Tabler Icons (MIT, Pawel Kuna): refresh, clock.
function Glyph({ name }) {
  const d = name === "refresh"
    ? "M20 11a8.1 8.1 0 0 0-15.5-2M4 5v4h4M4 13a8.1 8.1 0 0 0 15.5 2M20 19v-4h-4"
    : "M12 7v5l3 3";
  return (
    <svg className="info-glyph" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {name === "clock" && <circle cx="12" cy="12" r="9" />}
      <path d={d} />
    </svg>
  );
}

function KV({ k, v, mono = true, title }) {
  return <KVRow layout="grid" k={k} v={v} mono={mono} title={title} />;
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
    <KVRow layout="grid" k="Battery" mono={false}>
      <span className="bat">
        <span className={"bat-fill " + batteryTone(pct)} style={{ width: `${pct}%` }} />
      </span>
      <span className="mono">{pct}%</span>
      {mv ? <span className="info-dim mono">{mv} mV</span> : null}
    </KVRow>
  );
}

// The verdict as a short pill; the sentence under it still says the whole thing.
const PAIRING = {
  paired: { tone: "ok", text: "Halves paired" },
  "half-paired": { tone: "warn", text: "One half only" },
  "not-paired": { tone: "err", text: "Not bonded" },
  incomplete: { tone: "warn", text: "Both halves needed" },
  unknown: { tone: "warn", text: "No pair address" },
};

function HalfCard({ h, reference }) {
  const m = h.module;
  const behind = reference && h.firmwareVersion && h.firmwareVersion !== reference.createFirmware;
  const modBehind = reference && m?.firmwareVersion && m.firmwareVersion !== reference.moduleFirmware;
  return (
    <Card className="info-card" head={<span className={"dot " + (h.connected ? "ok" : "err")} />}
      title={h.description || h.side}
      actions={<Badge className="ui-badge-plain">{h.side === "dongle" ? "Dongle" : `${h.side[0].toUpperCase()}${h.side.slice(1)} half`}</Badge>}>
      {h.error && <Notice tone="err">{h.error}</Notice>}

      <div className="info-sub">Identity</div>
      <KV k="Firmware" v={h.firmwareVersion} />
      {behind && <div className="info-flag">Naya reference: {reference.createFirmware}</div>}
      <KV k="Hardware ID" v={h.hardwareId} />
      <KV k="USB product ID"
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
          {modBehind && <div className="info-flag">Naya reference: {reference.moduleFirmware}</div>}
          <KV k="Address" v={m.address != null ? `0x${m.address.toString(16).toUpperCase()}` : null} />
          <Battery pct={m.batteryPercent} mv={m.batteryMillivolts} />
        </>
      )}
    </Card>
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
  const { out, busy, run, clear } = useRunLog();
  const [live, setLive] = useState(false);   // read in this session, not restored from cache
  const [released, setReleased] = useState(false);
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

  // Hand the keyboard to another application, or take it back. Releasing closes the serial
  // ports and stands the poll down; nothing on the device changes either way.
  const toggleRelease = useCallback(async () => {
    setErr(null);
    try {
      const r = released ? await api.reconnectDevice() : await api.releaseDevice();
      setReleased(!!r.released);
    } catch (e) { setErr(e.message); }
  }, [released]);

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
    api.statusLast().then((r) => !cancelled && setReleased(!!r.released)).catch(() => {});
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
      <div className="page-head info-head">
        <div>
          <h1 className="page-title">Device information</h1>
          <p className="page-sub">Hardware, connections, and diagnostics for your Create.</p>
        </div>
        <div className="btn-row">
          <Button onClick={toggleRelease} variant={released ? "primary" : "secondary"}
            title={released
              ? "Open the keyboard again so OpenFlow can read and flash it"
              : "Close the serial ports so NayaFlow or another application can use the keyboard"}>
            {released ? "Reconnect keyboard" : "Release keyboard"}
          </Button>
          <Button onClick={refresh} disabled={loading || released}>
            <Glyph name="refresh" />
            {loading ? "Reading…" : at ? "Read again" : "Read device info"}
          </Button>
        </div>
      </div>

      {/* The tabs, with how old the reading is at the other end of the same row: it belongs to
          every tab, not to the button that refreshes it. */}
      <div className="info-tabrow">
        <Tabs variant="segmented" className="info-tabs" ariaLabel="Information sections" value={tab} onChange={setTab}
          items={[{ id: "device", label: "Device" }, { id: "connections", label: "Connections" }, { id: "troubleshooting", label: "Troubleshooting" }]} />
        <span className={"info-age" + (stale ? " stale" : "")}>
          <Glyph name="clock" />
          {at
            ? `Last ${live ? "read" : "reading"} ${ageText}`
            : "Reads over USB. Nothing is written."}
        </span>
      </div>

      {released && (
        <Notice tone="warn" className="info-released" title="The keyboard is released"
          action={<Button onClick={toggleRelease}>Reconnect</Button>}>
          OpenFlow has closed the serial ports and stopped polling, so another application can
          use the keyboard. Nothing here can read or flash until you reconnect. What is shown
          below is the last reading.
        </Notice>
      )}

      {err && <Notice tone="err" className="info-released" onDismiss={() => setErr(null)}>{err}</Notice>}

      {tab === "device" && (
        <>
          {!at && !loading && (
            <Card className="info-blank" title="Nothing read yet">
              <div className="setting-desc">
                Press <strong>Read device info</strong> to ask both halves who they are. It is a
                read-only USB query — nothing is written to the keyboard.
              </div>
            </Card>
          )}
          {recovery.length > 0 && (
            <div className="info-banner warn">
              <div className="info-banner-title">
                Bootloader
                <Badge tone="warn">
                  {recovery.length} half{recovery.length === 1 ? "" : "s"} in recovery
                </Badge>
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
            <Notice size="sm" tone="warn" className="info-stale-note">
              This reading is {ageText}. Firmware and addresses will not have changed, but battery
              and pairing may have — read again for those.
            </Notice>
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
                {p && <Badge className="ui-badge-plain" tone={p.tone}>{p.text}</Badge>}
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
            <Card className="info-card" ruled title="Bluetooth slots">
              {/* Which of the five slots the keyboard sends to, and what each holds. A state of
                  the keyboard, not a preference of the app, which is why it is here. */}
              <BleSlots />
            </Card>
            {halves.filter((h) => h.side === "dongle").length > 0
              ? halves.filter((h) => h.side === "dongle").map((h) => (
                  <HalfCard key={h.port} h={h} reference={sys?.reference} />
                ))
              : (
                <Card className="info-card" ruled title="Dongle"
                  actions={<Badge className="ui-badge-plain">Not on USB</Badge>} actionsAlign="end">
                  <Notice icon="info" title="Connect your dongle">
                    Plug it into USB, then read again to see its information.
                  </Notice>
                  <div className="info-sub">Firmware 3.07 limitation</div>
                  <div className="setting-desc">Wireless keyboard input is unavailable with this firmware.</div>
                  <Disclosure label="Technical details">
                    The dongle enumerates as its own serial device. Firmware 3.07 exposes no keyboard
                    interface, so it cannot bridge wireless keyboard input to this computer.
                  </Disclosure>
                </Card>
              )}
          </div>
        </>
      )}

      {tab === "troubleshooting" && (
        <>
          <div className="info-halves">
            <Card className="info-card" ruled title="Lighting">
              <div className="setting-desc" style={{ marginBottom: 10 }}>
                Restore puts both halves back to the profile's stored colors and animation after
                a lighting key changed them at runtime. On and off are the plain LED commands, per
                half.
              </div>
              <Button variant="primary" disabled={busy} className="info-lead-btn"
                onClick={() => lighting("Restore lighting", () => api.restoreLighting("left"))}>
                Restore lighting
              </Button>
              {["left", "right"].map((sd) => (
                <SettingRow key={sd} label={`${sd[0].toUpperCase()}${sd.slice(1)} half`}
                  control={
                    <span className="btn-row">
                      <Button size="sm" disabled={busy || (at != null && !connectedSides.includes(sd))}
                        onClick={() => lighting(`LEDs on (${sd})`, () => api.led(sd, "on"))}>
                        LEDs on
                      </Button>
                      <Button size="sm" disabled={busy || (at != null && !connectedSides.includes(sd))}
                        onClick={() => lighting(`LEDs off (${sd})`, () => api.led(sd, "off"))}>
                        LEDs off
                      </Button>
                    </span>
                  } />
              ))}
              <div className="setting-desc">On and off change the LEDs on that half.</div>
            </Card>
            <Card className="info-card" ruled title="Diagnostics"
              actions={<Badge className="ui-badge-plain">Read-only</Badge>} actionsAlign="end">
              <SettingRow bare className="info-runon" label="Run on"
                control={
                  <Tabs variant="segmented" ariaLabel="Half" value={side} onChange={setSide}
                    items={["left", "right", "dongle"].map((sd) => ({
                      id: sd, label: `${sd[0].toUpperCase()}${sd.slice(1)}`,
                      disabled: at != null && !connectedSides.includes(sd),
                      title: at != null && !connectedSides.includes(sd) ? "Not connected" : undefined,
                    }))} />
                } />
              <SettingRow label="Generate report" desc="Collect device information and diagnostics."
                control={<Button size="sm" disabled={busy}
                  onClick={() => run("Diagnostics report", api.diagnostics)}>Generate</Button>} />
              <SettingRow label="Dump settings" desc="Read the selected half's stored settings."
                control={<Button size="sm" disabled={busy}
                  onClick={() => run("Dump settings", () => api.dumpSettings(side))}>Read</Button>} />
              <SettingRow label="Test SPI flash" desc="Run the device's flash diagnostic."
                control={<Button size="sm" disabled={busy}
                  onClick={() => run("SPI flash self-test", () => api.sendCommand("repair_flash", [], { side }))}>Run test</Button>} />
              <div className="setting-desc info-runon-note">These checks do not change your bindings.</div>
              <Disclosure label="Recovery → Settings / Troubleshooting">
                Clearing Bluetooth bonds and wiping keymaps are managed in Settings &rsaquo;
                Troubleshooting, with a confirmation before data is erased.
              </Disclosure>
            </Card>
            <Card className="info-card info-span" ruled title="Software">
              <div className="info-software">
                <div>
                  <div className="info-sub info-sub-first">This computer</div>
                  <KV k="OpenFlow" v={sys?.backendVersion} />
                  <KV k="Operating system" v={sys ? `${sys.os} ${sys.osVersion}` : null} mono={false} />
                  <KV k="Architecture" v={sys?.arch} />
                  <KV k="Python" v={sys?.python} />
                </div>
                {sys?.reference && (
                  <div>
                    <div className="info-sub info-sub-first">Naya firmware reference</div>
                    <KV k="Create" v={sys.reference.createFirmware} />
                    <KV k="Module" v={sys.reference.moduleFirmware} />
                    <KV k="Source" v={sys.reference.source} mono={false} />
                  </div>
                )}
              </div>
            </Card>
          </div>
          {out && (
            <Card title="Output" actionsAlign="end" actions={<Button onClick={clear}>Clear</Button>}>
              <pre className="info-out">{out}</pre>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
