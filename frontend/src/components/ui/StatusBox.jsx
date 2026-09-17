// One keyboard half's live state as a box: the dot, L or R, Connected or Off, the battery as a
// number and a glyph; then the docked module with its picture and its battery. Fed from the
// devices stream, so it updates every six seconds. The profile bar's device chip renders two.
const MODULE_IMG = {
  touch: "/modules/touch.png",
  track: "/modules/track-plain.png",
  tune: "/modules/tune.png",
};

function batt(pct) {
  return pct == null ? "—" : `${pct}%`;
}

const low = (pct) => pct != null && pct <= 20;

// A battery outline with its level filled; green, or amber at 20% and under.
function Battery({ pct }) {
  const level = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <svg className={"ui-batt" + (low(pct) ? " low" : "")} viewBox="0 0 24 12" width="20" height="10" aria-hidden="true">
      <rect x="0.75" y="0.75" width="19.5" height="10.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="21.5" y="3.5" width="2" height="5" rx="0.8" fill="currentColor" />
      <rect x="2.75" y="2.75" width={(15.5 * level) / 100} height="6.5" rx="1" className="ui-batt-fill" />
    </svg>
  );
}

export default function StatusBox({ side, connected, batteryPercent, module, title, className = "", ...rest }) {
  const letter = side === "left" ? "L" : side === "right" ? "R" : "?";
  const cls = ["ui-statusbox", connected ? "" : "ui-statusbox-off", className].filter(Boolean).join(" ");
  const img = module && MODULE_IMG[String(module.type || "").toLowerCase()];
  return (
    <div {...rest} className={cls} title={title}>
      <div className="ui-statusbox-row">
        <span className={"dot " + (connected ? "ok" : "err")} />
        <span className="ui-statusbox-side">{letter}</span>
        <span className="ui-statusbox-state">{connected ? "Connected" : "Off"}</span>
        {connected && (
          <span className={"ui-statusbox-batt" + (low(batteryPercent) ? " low" : "")}>
            {batt(batteryPercent)}
            <Battery pct={batteryPercent} />
          </span>
        )}
      </div>
      <div className="ui-statusbox-row ui-statusbox-module">
        {connected && module ? (
          <>
            {img ? <img className="ui-statusbox-modimg" src={img} alt="" /> : <span className="ui-statusbox-modimg" />}
            <span>Module: <b>{module.type}</b></span>
            <span className={"ui-statusbox-batt" + (low(module.batteryPercent) ? " low" : "")}>
              {batt(module.batteryPercent)}
              <Battery pct={module.batteryPercent} />
            </span>
          </>
        ) : (
          <>
            <span className="ui-statusbox-modimg" />
            <span>{connected ? "No module" : "Not connected"}</span>
          </>
        )}
      </div>
    </div>
  );
}
