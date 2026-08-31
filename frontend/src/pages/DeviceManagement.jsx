import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

export default function DeviceManagement() {
  const [halves, setHalves] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.status();
      setHalves(res.halves || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function led(side, action, value) {
    try {
      await api.led(side, action, value);
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <div>
      <h1 className="page-title">Device Manager</h1>
      <p className="page-sub">
        Live status for connected halves and modules, read over USB CDC.
      </p>

      <div className="btn-row" style={{ marginBottom: 16 }}>
        <button className="btn" onClick={refresh} disabled={loading}>
          {loading ? "Reading…" : "Refresh status"}
        </button>
      </div>

      {err && <div className="card"><div className="phase-note">{err}</div></div>}

      {halves.length === 0 && !loading && (
        <div className="card">
          <div className="empty">No Naya Create detected. Connect a half via USB and refresh.</div>
        </div>
      )}

      <div className="grid">
        {halves.map((h) => (
          <div className="card" key={h.port}>
            <h3>
              {h.description}{" "}
              <span className="status">
                <span className={"dot " + (h.connected ? "ok" : "err")} />
              </span>
            </h3>
            {h.error && <div className="phase-note">{h.error}</div>}
            {h.firmwareVersion && (
              <div className="kv"><span className="k">Firmware</span><span className="v">{h.firmwareVersion}</span></div>
            )}
            {h.hardwareId && (
              <div className="kv"><span className="k">Hardware ID</span><span className="v">{h.hardwareId}</span></div>
            )}
            {h.bleAddress && (
              <div className="kv"><span className="k">BLE address</span><span className="v">{h.bleAddress}</span></div>
            )}
            {h.batteryPercent != null && (
              <div className="kv"><span className="k">Battery</span><span className="v">{h.batteryPercent}%</span></div>
            )}
            <div className="kv"><span className="k">Port</span><span className="v">{h.port}</span></div>

            {h.module && (
              <>
                <div className="kv"><span className="k">Module</span><span className="v">{h.module.type}</span></div>
                {h.module.firmwareVersion && (
                  <div className="kv"><span className="k">Module FW</span><span className="v">{h.module.firmwareVersion}</span></div>
                )}
                {h.module.batteryPercent != null && (
                  <div className="kv"><span className="k">Module battery</span><span className="v">{h.module.batteryPercent}%</span></div>
                )}
              </>
            )}

            {h.connected && (
              <div className="btn-row" style={{ marginTop: 14 }}>
                <button className="btn" onClick={() => led(h.side, "on")}>LEDs on</button>
                <button className="btn" onClick={() => led(h.side, "off")}>LEDs off</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
