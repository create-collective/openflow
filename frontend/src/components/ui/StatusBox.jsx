// One keyboard half's live state on a line: the dot, L or R, connected or off, the battery;
// with the docked module and its battery on a second line. Fed from the devices stream, so it
// updates every six seconds. The profile bar's device chip renders two of these.
function batt(pct) {
  return pct == null ? "—" : `${pct}%`;
}

const low = (pct) => pct != null && pct <= 20;

export default function StatusBox({ side, connected, batteryPercent, module, title, className = "", ...rest }) {
  const letter = side === "left" ? "L" : side === "right" ? "R" : "?";
  const cls = ["ui-statusbox", className].filter(Boolean).join(" ");
  return (
    <div {...rest} className={cls} title={title}>
      <div className="ui-statusbox-row">
        <span className={"dot " + (connected ? "ok" : "err")} />
        <span className="ui-statusbox-side">{letter}</span>
        <span>{connected ? "connected" : "off"}</span>
        <span className={"ui-statusbox-batt" + (low(batteryPercent) ? " low" : "")}>
          {connected ? batt(batteryPercent) : ""}
        </span>
      </div>
      {connected && module && (
        <div className="ui-statusbox-row ui-statusbox-module">
          <span>{module.type}</span>
          <span className={"ui-statusbox-batt" + (low(module.batteryPercent) ? " low" : "")}>
            {batt(module.batteryPercent)}
          </span>
        </div>
      )}
    </div>
  );
}
