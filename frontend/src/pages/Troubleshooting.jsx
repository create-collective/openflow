import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

// The page the nav calls "Information". It used to show none: three action buttons and a raw
// JSON dump, with every action hardcoded to the left half. Everything it needed was already one
// read away in the backend and simply never asked for.
//
// It answers two questions. "What do I have?" -- per half and per module, with the firmware you
// are running set against the firmware Naya ships. And "is it healthy?" -- specifically whether
// a half that seems missing is actually dead or merely no longer bonded to its partner, which
// look identical from the outside and need opposite repairs.

function KV({ k, v, mono = false, title }) {
  if (v === null || v === undefined || v === "") return null;
  return (
    <div className="kv" title={title}>
      <span className="k">{k}</span>
      <span className="v" style={mono ? { fontFamily: "var(--font-mono)" } : undefined}>{v}</span>
    </div>
  );
}

const PAIRING = {
  paired: { pill: "ok", text: "Halves are bonded to each other" },
  "half-paired": { pill: "warn", text: "Only one half points at its partner" },
  "not-paired": { pill: "err", text: "Halves are not bonded to each other" },
  incomplete: { pill: "warn", text: "Both halves must be connected to check" },
  unknown: { pill: "warn", text: "Neither half reported a pair address" },
};

function HalfCard({ h, reference }) {
  const m = h.module;
  // Naya ships one firmware per generation; if the half is behind, that is worth seeing next to
  // the version rather than buried in a separate screen.
  const behind = reference && h.firmwareVersion && h.firmwareVersion !== reference.createFirmware;
  const modBehind = reference && m?.firmwareVersion && m.firmwareVersion !== reference.moduleFirmware;
  return (
    <div className="card">
      <h3>
        {h.description || h.side}
        <span className={"dot " + (h.connected ? "ok" : "err")} />
      </h3>
      {h.error && <div className="phase-note">{h.error}</div>}

      <KV k="Side" v={h.side} />
      <KV k="Firmware" mono
        v={h.firmwareVersion ? (behind ? `${h.firmwareVersion} (Naya ships ${reference.createFirmware})`
                                       : h.firmwareVersion) : null} />
      <KV k="Hardware ID" v={h.hardwareId} mono />
      <KV k="Serial" v={h.serialNumber} mono />
      <KV k="USB product id" v={h.pid != null ? `0x${h.pid.toString(16).toUpperCase().padStart(4, "0")}` : null}
        mono title="Identifies which half this is, and which firmware image it would take." />
      <KV k="Port" v={h.port} mono />
      <KV k="Battery" v={h.batteryPercent != null
        ? `${h.batteryPercent}%${h.batteryMillivolts ? ` (${h.batteryMillivolts} mV)` : ""}` : null} />

      {h.ble && (
        <>
          <div className="info-sub">Bluetooth</div>
          <KV k="Name" v={h.ble.name || "(unset)"} />
          <KV k="Address" v={h.bleAddress} mono />
          <KV k="Paired to" v={h.ble.pairAddress} mono
            title="The address this half is bonded to. On a healthy pair this is the other half's address." />
          <KV k="Dongle" v={h.ble.dongleAddress} mono />
          <KV k="Radio firmware" v={h.ble.firmwareVersion} mono />
        </>
      )}

      {m && (
        <>
          <div className="info-sub">Docked module</div>
          <KV k="Type" v={m.type} />
          <KV k="Firmware" mono
            v={m.firmwareVersion ? (modBehind ? `${m.firmwareVersion} (Naya ships ${reference.moduleFirmware})`
                                              : m.firmwareVersion) : null} />
          <KV k="Address" v={m.address != null ? `0x${m.address.toString(16).toUpperCase()}` : null} mono />
          <KV k="Docked on" v={m.docked} />
          <KV k="Battery" v={m.batteryPercent != null
            ? `${m.batteryPercent}%${m.batteryMillivolts ? ` (${m.batteryMillivolts} mV)` : ""}` : null} />
        </>
      )}
    </div>
  );
}

export default function Troubleshooting() {
  const [halves, setHalves] = useState([]);
  const [pairing, setPairing] = useState(null);
  const [sys, setSys] = useState(null);
  const [at, setAt] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [side, setSide] = useState("left");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);   // read in this session, not restored from cache

  const refresh = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await api.statusDeep();
      setHalves(r.halves || []);
      setPairing(r.pairing || null);
      setAt(r.at ? new Date(r.at + "Z") : new Date());
      setLive(true);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, []);

  // System info is free (no USB), so it loads on mount. The device read is NOT, so the page
  // paints the last one from cache and only re-reads on a click -- the same bargain Device
  // Manager makes. Without this the page went blank every time you navigated away and back,
  // and re-reading five extra BLE round trips per half to redraw what we already knew.
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

  async function run(label, fn) {
    setBusy(true); setOut(`${label}…`);
    try { const res = await fn(); setOut(`${label}:\n${JSON.stringify(res, null, 2)}`); }
    catch (e) { setOut(`${label} failed:\n${e.message}`); }
    finally { setBusy(false); }
  }

  const connectedSides = halves.filter((h) => h.connected).map((h) => h.side);
  const p = pairing && PAIRING[pairing.state];

  return (
    <div>
      <h1 className="page-title">Information</h1>
      <p className="page-sub">
        What is connected, what firmware it runs, and whether the halves can see each other.
      </p>

      <div className="btn-row" style={{ marginBottom: 16, alignItems: "center" }}>
        <button className="btn primary" onClick={refresh} disabled={loading}>
          {loading ? "Reading…" : "Read device info"}
        </button>
        {at && (
          <span className="saved-note">
            {live ? "read " : "as of "}{at.toLocaleTimeString()}
            {!live && " (cached)"}
          </span>
        )}
        {!at && <span className="saved-note">Reads over USB. Nothing is written.</span>}
      </div>

      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      {pairing && (
        <div className="card">
          <h3>Split link {p && <span className={"pill " + p.pill}>{p.text}</span>}</h3>
          <div className="setting-desc">{pairing.detail}</div>
          {pairing.state !== "paired" && pairing.state !== "incomplete" && (
            <div className="phase-note" style={{ marginTop: 10 }}>
              Both halves are talking to this computer over USB, so neither is dead — they are
              just not bonded to each other. Re-pairing is the repair here, not a firmware update.
            </div>
          )}
          {pairing.state === "incomplete" && connectedSides.length > 0 && (
            <div className="phase-note" style={{ marginTop: 10 }}>
              Only the {connectedSides.join(" and ")} half answered over USB. If a half is missing,
              connect it directly with its own USB-C cable and read again — each half enumerates
              on its own, so one can be reached even when the other cannot see it.
            </div>
          )}
        </div>
      )}

      {halves.length > 0 && (
        <div className="grid">
          {halves.map((h) => <HalfCard key={h.port} h={h} reference={sys?.reference} />)}
        </div>
      )}

      <div className="card">
        <h3>Software</h3>
        <KV k="OpenFlow" v={sys?.backendVersion} mono />
        <KV k="Operating system" v={sys ? `${sys.os} ${sys.osVersion} (${sys.arch})` : null} />
        <KV k="Python" v={sys?.python} mono />
        {sys?.reference && (
          <>
            <div className="info-sub">Reference firmware</div>
            <KV k="Create" v={sys.reference.createFirmware} mono />
            <KV k="Module" v={sys.reference.moduleFirmware} mono />
            <KV k="Source" v={sys.reference.source} />
          </>
        )}
      </div>

      <div className="card">
        <h3>Diagnostics</h3>
        <div className="btn-row" style={{ marginBottom: 10 }}>
          {["left", "right", "dongle"].map((s) => (
            <button key={s} className={"btn" + (side === s ? " primary" : "")}
              onClick={() => setSide(s)}>
              {s}{connectedSides.includes(s) ? "" : " (not connected)"}
            </button>
          ))}
        </div>
        <div className="btn-row">
          <button className="btn" disabled={busy} onClick={() => run("Diagnostics report", api.diagnostics)}>
            Generate report
          </button>
          <button className="btn" disabled={busy} onClick={() => run("Dump settings", () => api.dumpSettings(side))}>
            Dump on-device settings
          </button>
          <button className="btn" disabled={busy}
            onClick={() => run("SPI flash self-test", () => api.sendCommand("repair_flash", [], { side }))}>
            Test SPI flash (read-only)
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Recovery <span className="pill err">destructive</span></h3>
        <div className="phase-note" style={{ marginBottom: 12 }}>
          This clears Bluetooth bonds on the <strong>{side}</strong> half. If the halves are
          bonded to each other, clearing them means re-pairing afterwards.
        </div>
        <div className="btn-row">
          <button className="btn danger" disabled={busy}
            onClick={() => {
              if (confirm(`Clear all Bluetooth bonds on the ${side} half?`)) {
                run("Clear BLE devices", () => api.sendCommand("clear_ble_devices", [], { side, force: true }));
              }
            }}>
            Clear BLE devices ({side})
          </button>
        </div>
      </div>

      {out && (
        <div className="card">
          <h3>Output</h3>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", margin: 0 }}>{out}</pre>
        </div>
      )}
    </div>
  );
}
