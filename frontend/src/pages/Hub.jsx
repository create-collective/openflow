import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useSSE } from "../lib/useSSE";

export default function Hub() {
  const [sys, setSys] = useState(null);
  const [err, setErr] = useState(null);
  const { data: deviceStream, connected } = useSSE("sse:naya-devices-stream");

  useEffect(() => {
    api.systemInfo().then(setSys).catch((e) => setErr(e.message));
  }, []);

  const devices = deviceStream?.devices ?? [];

  return (
    <div>
      <h1 className="page-title">OpenFlow</h1>
      <p className="page-sub">
        Open-source companion for the Naya Create — no cloud, no external
        dependencies.
      </p>

      <div className="grid">
        <div className="card">
          <h3>Backend</h3>
          <div className="status">
            <span className={"dot " + (connected ? "ok" : "err")} />
            {connected ? "Connected" : "Offline"}
          </div>
          {sys && (
            <>
              <div className="kv">
                <span className="k">Version</span>
                <span className="v">{sys.backendVersion}</span>
              </div>
              <div className="kv">
                <span className="k">OS</span>
                <span className="v">{sys.os} {sys.arch}</span>
              </div>
            </>
          )}
          {err && <div className="phase-note">{err}</div>}
        </div>

        <div className="card">
          <h3>Devices</h3>
          {devices.length === 0 ? (
            <div className="empty">No Naya Create detected. Connect via USB.</div>
          ) : (
            devices.map((d) => (
              <div className="kv" key={d.port}>
                <span className="k">{d.description}</span>
                <span className="v">{d.port}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
