// One setting control, shared by the Settings page and the Modules settings tab.
//
// The Modules tab carried an inlined copy of this: same markup, duplicated, supporting only
// toggle and slider (no select) and with its own "app only" marker that Settings did not have.
// Two copies of one control is how they drift -- the copy never gained the numeric box, the
// min/max labels, or a working Reset on toggles.
//
// What we can actually prove about a setting, straight from the backend's `provenance`.
// Seven settings used to say "Flashed to the device" while none of them reached it, so the
// honest thing is to say per setting how much is known -- and the experimental set doubles as
// the queue of things to go and probe.
const PROVENANCE = {
  verified: { label: "verified", title: "Confirmed to reach the keyboard." },
  experimental: {
    label: "experimental",
    title: "Stored, but OpenFlow does not send it to the keyboard yet. Changing it will not "
         + "affect how the board behaves.",
  },
  app: { label: "app only", title: "An OpenFlow preference. Never sent to the keyboard." },
  host: {
    label: "host-side",
    title: "Handled on the computer (Create Companion's model), not flashed to the keyboard. "
         + "There is no firmware setting behind it, so this is not something to probe.",
  },
};

export default function SettingField({ f, onChange }) {
  // Toggles were excluded here, so led_scan_mode and tray_battery could never be reset.
  const changed = f.default !== undefined && f.value !== f.default;
  const prov = PROVENANCE[f.provenance];
  // A setting that has no home yet in the browser dev build -- the system-tray battery needs the
  // Electron shell. Shown, but inert and labelled, rather than offering a switch that does nothing.
  if (f.deferred) {
    return (
      <div className="setting setting-deferred">
        <div className="setting-head">
          <strong>{f.label}</strong>
          <span className="gesture-badge prov-app" title={f.deferred}>{f.deferred_badge || "desktop app"}</span>
        </div>
        <div className="setting-desc">{f.desc}</div>
      </div>
    );
  }
  const resetLabel = f.kind === "toggle" ? (f.default ? "on" : "off") : `${f.default}${f.unit || ""}`;
  return (
    <div className="setting">
      <div className="setting-head">
        <strong>{f.label}</strong>
        {prov && (
          <span className={"gesture-badge prov-" + f.provenance} title={prov.title}>
            {prov.label}
          </span>
        )}
        <div className="setting-ctl">
          {changed && (
            <button className="setting-reset" title={`Reset to ${resetLabel}`}
              onClick={() => onChange(f.id, f.default)}>↺ Reset</button>
          )}
          {f.kind === "toggle" ? (
            <button className={"toggle" + (f.value ? " on" : "")} onClick={() => onChange(f.id, !f.value)}>
              <span className="toggle-knob" />
            </button>
          ) : f.kind === "select" ? (
            <select className="mac-input" value={f.value} onChange={(e) => onChange(f.id, e.target.value)}>
              {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            // A number box, because these ranges are unusable as a bare slider: idle_timeout_s
            // is 0-6000 across ~600px, so one pixel is ten seconds and the exact value you want
            // is unreachable by dragging.
            <input type="number" className="mac-input setting-num"
              min={f.min} max={f.max} value={f.value}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (Number.isFinite(n)) onChange(f.id, Math.min(f.max, Math.max(f.min, n)));
              }} />
          )}
        </div>
      </div>
      <div className="setting-desc">{f.desc}</div>
      {f.kind === "slider" && (
        <div className="setting-slider">
          <span className="setting-bound">{f.min}{f.unit}</span>
          <input
            type="range" min={f.min} max={f.max} value={f.value}
            onChange={(e) => onChange(f.id, Number(e.target.value))}
          />
          <span className="setting-bound">{f.max}{f.unit}</span>
        </div>
      )}
    </div>
  );
}
