import { useRef } from "react";
import { NavLink } from "react-router-dom";
import StatusBox from "./ui/StatusBox";

// The status chip NayaFlow keeps in its top-left corner, rebuilt in the profile bar: one
// StatusBox per half (the dot, L or R, connected, battery; the docked module beneath). It
// reads the poll loop's snapshot off the devices stream, so it updates every six seconds
// without anyone pressing Refresh. Hover a half for the detail; click for the Devices page.
function detailsFor(h) {
  const m = h.module;
  const mv = (pct, mV) => (pct == null ? null : mV != null ? `${pct}% (${mV} mV)` : `${pct}%`);
  return [
    ["Half", h.description || (h.side === "left" ? "Create Left" : "Create Right")],
    // Only worth saying when there is more than one, otherwise it is noise on every hover.
    ["Keyboard", (h.keyboardCount || 1) > 1 ? `${(h.keyboardId ?? 0) + 1} of ${h.keyboardCount}` : null],
    ["Serial", (h.keyboardCount || 1) > 1 ? h.serialNumber || null : null],
    ["State", h.connected ? "Connected" : "Disconnected"],
    ["Error", h.error || null],
    ["Firmware", h.firmwareVersion || null],
    ["Battery", h.connected ? mv(h.batteryPercent, h.batteryMillivolts) : null],
    ["Module", m ? `${m.type} docked` : (h.connected ? "None" : null)],
    ["Module battery", m ? mv(m.batteryPercent, m.batteryMillivolts ?? m.voltage) : null],
    ["Module firmware", m?.firmwareVersion || null],
    ["Read", h.at ? new Date(h.at).toLocaleTimeString() : null],
  ].filter(([, v]) => v !== null && v !== undefined);
}

export default function DeviceChip({ status }) {
  const halves = status?.halves || [];
  // A poll now and then answers with the module but no battery for it. The device does report
  // it the next time round, so rather than flashing a dash for six seconds the box keeps the
  // last figure it had for that module in that bay.
  const lastBattery = useRef({});
  const withHeldBattery = (h) => {
    if (!h.module) return h;
    // Keyed by the HALF, not the side: with two keyboards attached there are two lefts,
    // and keying on the side made them share a held battery figure.
    const key = `${h.serialNumber || h.port}:${h.module.type}`;
    if (h.module.batteryPercent != null) {
      lastBattery.current[key] = h.module.batteryPercent;
      return h;
    }
    const held = lastBattery.current[key];
    return held == null ? h : { ...h, module: { ...h.module, batteryPercent: held } };
  };
  // One group per physical keyboard. `keyboardId` comes from the backend, which joins halves
  // by BLE identity, so the bar and the Devices page cannot disagree about which two belong
  // together. Without it this rendered `key={h.side}` -- two halves keyed "left" and two keyed
  // "right" -- and React reconciled the duplicates arbitrarily on every six-second poll, which
  // is why the left flipped between boards and one right never appeared at all.
  const shown = halves.map(withHeldBattery);
  const boards = [];
  for (const h of shown) {
    const id = h.keyboardId ?? 0;
    const found = boards.find((b) => b.id === id);
    if (found) found.halves.push(h);
    else boards.push({ id, halves: [h] });
  }

  return (
    <NavLink to="/information" className="device-chip" title={halves.length ? undefined : "No keyboard on USB"}>
      {halves.length === 0
        ? <div className="device-chip-empty">No keyboard</div>
        : boards.map((b, n) => (
          <span key={b.id} className="device-chip-board"
            title={boards.length > 1 ? `Keyboard ${n + 1} of ${boards.length}` : undefined}>
            {b.halves.map((h) => (
              <StatusBox key={h.serialNumber || h.port} side={h.side} connected={h.connected}
                batteryPercent={h.batteryPercent} module={h.module} details={detailsFor(h)} />
            ))}
          </span>
        ))}
    </NavLink>
  );
}
