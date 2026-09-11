import { NavLink } from "react-router-dom";

// The status chip NayaFlow keeps in its top-left corner, rebuilt: one row per half with its
// battery, the docked module beneath. It reads the poll loop's snapshot off the devices stream,
// so it updates every six seconds without anyone pressing Refresh. Hover for the detail; click
// for the Information page.
function batt(pct) {
  return pct == null ? "—" : `${pct}%`;
}

function Row({ h }) {
  const side = h.side === "left" ? "L" : h.side === "right" ? "R" : "?";
  const title = [
    `${h.description || h.side}: ${h.connected ? "connected" : "disconnected"}`,
    h.error ? h.error : null,
    h.firmwareVersion ? `firmware ${h.firmwareVersion}` : null,
    h.batteryMillivolts != null ? `battery ${h.batteryPercent}% (${h.batteryMillivolts} mV)` : null,
    h.module ? `${h.module.type} docked${h.module.batteryPercent != null ? `, ${h.module.batteryPercent}%` : ""}` : "no module",
    h.at ? `read ${new Date(h.at).toLocaleTimeString()}` : null,
  ].filter(Boolean).join("\n");
  return (
    <>
      <div className="device-chip-row" title={title}>
        <span className={"dot " + (h.connected ? "ok" : "err")} />
        <span className="device-chip-side">{side}</span>
        <span>{h.connected ? "connected" : "off"}</span>
        <span className={"device-chip-batt" + (h.batteryPercent != null && h.batteryPercent <= 20 ? " low" : "")}>
          {h.connected ? batt(h.batteryPercent) : ""}
        </span>
      </div>
      {h.connected && h.module && (
        <div className="device-chip-row device-chip-module" title={title}>
          <span>{h.module.type}</span>
          <span className={"device-chip-batt" + (h.module.batteryPercent != null && h.module.batteryPercent <= 20 ? " low" : "")}>
            {batt(h.module.batteryPercent)}
          </span>
        </div>
      )}
    </>
  );
}

export default function DeviceChip({ status }) {
  const halves = status?.halves || [];
  return (
    <NavLink to="/information" className="device-chip" title={halves.length ? undefined : "No keyboard on USB"}>
      {halves.length === 0
        ? <div className="device-chip-empty">No keyboard</div>
        : halves.map((h) => <Row key={h.side} h={h} />)}
    </NavLink>
  );
}
