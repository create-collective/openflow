import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useDeviceStream } from "../lib/deviceStream";
import Card from "../components/ui/Card";
import { KVRow } from "../components/ui/KV";
import Notice from "../components/ui/Notice";

export default function Hub() {
  const [sys, setSys] = useState(null);
  const [err, setErr] = useState(null);
  const { data: deviceStream, connected } = useDeviceStream();

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
        <Card title="Backend">
          <div className="status">
            <span className={"dot " + (connected ? "ok" : "err")} />
            {connected ? "Connected" : "Offline"}
          </div>
          {sys && (
            <>
              <KVRow k="Version" v={sys.backendVersion} />
              <KVRow k="OS" v={`${sys.os} ${sys.arch}`} />
            </>
          )}
          {err && <Notice tone="err">{err}</Notice>}
        </Card>

        <Card title="Devices">
          {devices.length === 0 ? (
            <div className="empty">No Naya Create detected. Connect via USB.</div>
          ) : (
            devices.map((d) => <KVRow key={d.port} k={d.description} v={d.port} />)
          )}
        </Card>
      </div>
    </div>
  );
}
