import { KVList, KVRow } from "./KV";

// One keyboard half's live state as a box: the dot, L or R, Connected or Off, the battery as a
// number and a glyph; then the docked module with its picture and its battery. Fed from the
// devices stream, so it updates every six seconds. The profile bar's device chip renders two.
// `details` ([label, value] pairs) opens under the box on hover, styled like the app's menus,
// for what the box has no room for: firmware, millivolts, the module's firmware, the read time.
// The picture follows the bay it is docked in. A Track has two physically different units;
// a Touch is one part that presents its mirror image depending on the bay. Only the Tune,
// being a dial, looks the same either way.
function moduleImg(type, side) {
  const t = String(type || "").toLowerCase();
  const hand = side === "right" ? "right" : "left";
  if (t === "track" || t === "touch") return `/modules/v2/${t}-${hand}.png`;
  return t === "tune" ? "/modules/v2/tune.png" : null;
}

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

export default function StatusBox({
  side, connected, batteryPercent, module, details = null, title, className = "", ...rest
}) {
  const letter = side === "left" ? "L" : side === "right" ? "R" : "?";
  const cls = ["ui-statusbox", connected ? "" : "ui-statusbox-off", className].filter(Boolean).join(" ");
  const img = module && moduleImg(module.type, module.docked || side);
  return (
    <div {...rest} className={cls} title={details ? undefined : title} tabIndex={details ? 0 : undefined}>
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
      {details && details.length > 0 && (
        <div className="ui-statusbox-tip" role="tooltip">
          <KVList>
            {details.map(([k, v]) => <KVRow key={k} k={k} v={v} mono={false} />)}
          </KVList>
        </div>
      )}
    </div>
  );
}
