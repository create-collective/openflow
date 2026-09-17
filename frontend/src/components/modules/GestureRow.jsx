import Badge from "../ui/Badge";
import { shortcutInfo, shortcutTooltip } from "../../lib/shortcutNames";
import { cleanCode, displayAction, gestureName, GESTURE_LABEL, statusBadge } from "../../lib/moduleLabels";

// What the keyboard has for one gesture, or one half of one. Shared, because the axis halves
// were hand-built rows that simply never rendered it, so a split Tune axis showed no ON DEVICE
// mark while the dial (whose halves are separate behaviors, and so go through GestureRow) did.
export function DeviceBadge({ dev }) {
  if (!dev) return null;
  return (
    <Badge
      size="xs"
      tone={dev.differs ? "neutral" : "ok"}
      title={dev.differs
        ? `On the keyboard this is ${dev.device ?? "unbound"}; the app has ${dev.app || "nothing"}. Flash to make them match.`
        : `Matches what is on the keyboard (field ${"0x" + (dev.field ?? 0).toString(16)}).`}
    >
      {dev.differs ? `device: ${dev.device ?? "unbound"}` : "on device"}
    </Badge>
  );
}

// One gesture row: gesture label, status badge, what the keyboard has, the arrow, the action.
// Clicking selects it as the palette's target; `extra` is the row's own controls (invert, split).
export default function GestureRow({ b, dev, extra, selected, onSelect, labelFor = cleanCode }) {
  // A Track hold has no device field at all: the capture showed NayaFlow writing the hold value
  // over the tap and the tap never reaching the board. Offering it as editable would be
  // offering to lose the tap, so it renders disabled. A split parent is different: it is
  // supported, its value simply lives on the two half rows, so it is disabled but must not
  // wear the "experimental" badge, which is specifically about a binding the hardware cannot
  // store.
  const unsupported = /^hold:track:button_/.test(b.behavior || "");
  const splitParent = !!b.pairedSplit;
  // Firmware-driven (the Touch's taps and one-finger cursor): shown, never selectable. The
  // value displayed is what the firmware does, from the server, not a row the user set.
  const locked = !!b.locked;
  const badge = statusBadge({ unsupported, flashable: b.flashable, locked });
  // A split parent and an unsupported row show PLACEHOLDER text, not a value, so they are
  // muted like an unassigned row.
  const shown = splitParent ? { text: "set per direction below", muted: true }
    : unsupported ? { text: "not settable", muted: true }
    : locked ? { text: `${displayAction(b.firmwareDefault || "", labelFor).text} (firmware)`, muted: true }
    : displayAction(b.actionCode, labelFor);
  const title = splitParent
    ? "Split is on — each direction is set separately below."
    : locked
    ? "Driven by the module firmware. The field is flashed empty and cannot be rebound here or in NayaFlow."
    : unsupported
    ? "The Track cannot store a hold — setting one would overwrite the tap."
    : shown.title
      || (shortcutInfo(b.actionCode) ? shortcutTooltip(b.actionCode) : "Click the row, then pick an action below.");
  return (
    <div
      className={"skp-row" + (selected ? " selected" : "")}
      style={onSelect && !locked ? undefined : { cursor: "default" }}
      onClick={onSelect && !locked ? () => onSelect(b.id) : undefined}
    >
      <span className={"skp-beh " + (GESTURE_LABEL[b.gesture] ? "skp-beh-plain" : "skp-beh-caps")}>
        {gestureName(b.gesture)}
      </span>
      <Badge size="xs" tone={badge.tone} title={badge.title}>{badge.text}</Badge>
      <DeviceBadge dev={dev} />
      <span className="skp-arrow" title={shortcutTooltip(b.actionCode)}>→</span>
      <span className={"skp-act" + (shown.muted ? " unset" : "")} title={title}>{shown.text}</span>
      {extra}
    </div>
  );
}
