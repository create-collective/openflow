import { useState } from "react";
import { api } from "../lib/api";

export default function Troubleshooting() {
  const [side, setSide] = useState("left");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(label, fn) {
    setBusy(true);
    setOut(`${label}…`);
    try {
      const res = await fn();
      setOut(`${label}:\n${JSON.stringify(res, null, 2)}`);
    } catch (e) {
      setOut(`${label} failed:\n${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">Information &amp; Troubleshooting</h1>
      <p className="page-sub">Read-only diagnostics and safe recovery tools.</p>

      <div className="card">
        <h3>Target half</h3>
        <div className="btn-row">
          {["left", "right", "dongle"].map((s) => (
            <button
              key={s}
              className={"btn" + (side === s ? " primary" : "")}
              onClick={() => setSide(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Diagnostics</h3>
        <div className="btn-row">
          <button className="btn" disabled={busy} onClick={() => run("Diagnostics report", api.diagnostics)}>
            Generate report
          </button>
          <button className="btn" disabled={busy} onClick={() => run("Dump settings", () => api.dumpSettings(side))}>
            Dump on-device settings
          </button>
          <button className="btn" disabled={busy} onClick={() => run("SPI flash self-test", () => api.sendCommand("repair_flash", [], { side }))}>
            Test SPI flash (read-only)
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Recovery <span className="pill">destructive</span></h3>
        <div className="phase-note" style={{ marginBottom: 12 }}>
          These clear data on the device. They require an explicit confirmation
          (force) and are wired conservatively during Phase 1.
        </div>
        <div className="btn-row">
          <button
            className="btn danger"
            disabled={busy}
            onClick={() => {
              if (confirm("Clear all Bluetooth bonds on the " + side + " half?")) {
                run("Clear BLE devices", () => api.sendCommand("clear_ble_devices", [], { side, force: true }));
              }
            }}
          >
            Clear BLE devices
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
