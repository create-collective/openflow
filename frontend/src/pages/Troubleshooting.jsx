import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

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

  async function run(label, fn) {
    setBusy(true); setOut(`${label}…`);
    try { const res = await fn(); setOut(`${label}:\n${JSON.stringify(res, null, 2)}`); }
    catch (e) { setOut(`${label} failed:\n${e.message}`); }
    finally { setBusy(false); }
  }

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
          <span className="saved-note">
            {at
              ? `${live ? "read" : "as of"} ${at.toLocaleTimeString()}${live ? "" : " (cached)"}`
              : "Reads over USB. Nothing is written."}
          </span>
        </div>
      </div>

      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      {!at && !loading && (
        <div className="card info-blank">
          <h3>Nothing read yet</h3>
          <div className="setting-desc">
            Press <strong>Read device info</strong> to ask both halves who they are. It is a
            read-only USB query — nothing is written to the keyboard.
          </div>
        </div>
      )}

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

      {halves.length > 0 && (
        <div className="info-halves">
          {halves.map((h) => <HalfCard key={h.port} h={h} reference={sys?.reference} />)}
        </div>
      )}

      <div className="info-halves">
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

        <div className="card info-card">
          <div className="info-card-head"><h3>Diagnostics</h3></div>
          <div className="setting-desc" style={{ marginBottom: 10 }}>
            Run against a chosen half. These read the device; none of them change a binding.
          </div>
          <div className="seg">
            {["left", "right", "dongle"].map((s) => (
              <button key={s}
                className={"seg-btn" + (side === s ? " active" : "")}
                disabled={at != null && !connectedSides.includes(s)}
                title={at != null && !connectedSides.includes(s) ? "Not connected" : undefined}
                onClick={() => setSide(s)}>
                {s}
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
    </div>
  );
}
