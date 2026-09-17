import { NavLink } from "react-router-dom";
import StatusBox from "./ui/StatusBox";

// The status chip NayaFlow keeps in its top-left corner, rebuilt in the profile bar: one
// StatusBox per half (the dot, L or R, connected, battery; the docked module beneath). It
// reads the poll loop's snapshot off the devices stream, so it updates every six seconds
// without anyone pressing Refresh. Hover for the detail; click for the Devices page.
function describe(h) {
  return [
    `${h.description || h.side}: ${h.connected ? "connected" : "disconnected"}`,
    h.error ? h.error : null,
    h.firmwareVersion ? `firmware ${h.firmwareVersion}` : null,
    h.batteryMillivolts != null ? `battery ${h.batteryPercent}% (${h.batteryMillivolts} mV)` : null,
    h.module ? `${h.module.type} docked${h.module.batteryPercent != null ? `, ${h.module.batteryPercent}%` : ""}` : "no module",
    h.at ? `read ${new Date(h.at).toLocaleTimeString()}` : null,
  ].filter(Boolean).join("\n");
}

export default function DeviceChip({ status }) {
  const halves = status?.halves || [];
  return (
    <NavLink to="/information" className="device-chip" title={halves.length ? undefined : "No keyboard on USB"}>
      {halves.length === 0
        ? <div className="device-chip-empty">No keyboard</div>
        : halves.map((h) => (
          <StatusBox key={h.side} side={h.side} connected={h.connected} batteryPercent={h.batteryPercent}
            module={h.module} title={describe(h)} />
        ))}
    </NavLink>
  );
}
