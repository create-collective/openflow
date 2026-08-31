import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function Settings() {
  const [updates, setUpdates] = useState(null);

  useEffect(() => {
    api.checkForUpdates().then(setUpdates).catch(() => setUpdates(null));
  }, []);

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Application preferences.</p>

      <div className="card">
        <h3>Updates</h3>
        <div className="phase-note">
          OpenFlow has no external update dependency by design. Unlike NayaFlow, it
          does not call GitHub or any cloud service at runtime.
        </div>
        {updates && (
          <div className="kv" style={{ marginTop: 12 }}>
            <span className="k">Status</span>
            <span className="v">{updates.updateAvailable ? "Update available" : "Up to date"}</span>
          </div>
        )}
      </div>

      <div className="card">
        <h3>About</h3>
        <div className="kv"><span className="k">Application</span><span className="v">OpenFlow</span></div>
        <div className="kv"><span className="k">Protocol</span><span className="v">nayactl (Apache-2.0)</span></div>
      </div>
    </div>
  );
}
