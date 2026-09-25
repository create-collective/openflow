import { useState } from "react";
import Badge from "./ui/Badge";
import SettingRow from "./ui/SettingRow";
import Toggle from "./ui/Toggle";

// One setting control, shared by the Settings page and the Modules settings tab.
//
// The Modules tab carried an inlined copy of this: same markup, duplicated, supporting only
// toggle and slider (no select) and with its own "app only" marker that Settings did not have.
// Two copies of one control is how they drift -- the copy never gained the numeric box, the
// min/max labels, or a working Reset on toggles. The row itself (label, badge, control, reset,
// description) is SettingRow; this picks the control for the setting's kind.
//
// What we can actually prove about a setting, straight from the backend's `provenance`.
// Seven settings used to say "Flashed to the device" while none of them reached it, so the
// honest thing is to say per setting how much is known -- and the experimental set doubles as
// the queue of things to go and probe.
const PROVENANCE = {
  verified: { label: "verified", tone: "ok", title: "Confirmed to reach the keyboard." },
  experimental: {
    label: "experimental",
    tone: "warn",
    title: "Stored, but OpenFlow does not send it to the keyboard yet. Changing it will not "
         + "affect how the board behaves.",
  },
  app: { label: "app only", tone: "neutral", title: "An OpenFlow preference. Never sent to the keyboard." },
  host: {
    label: "host-side",
    tone: "neutral",
    title: "Handled on the computer (Create Companion's model), not flashed to the keyboard. "
         + "There is no firmware setting behind it, so this is not something to probe.",
  },
};

// A setting the device stores in another unit can only hold some values; the backend sends
// them as `steps` (ticks per rotation: 360 / whole degrees, so 72, 90, 120, 180 but not 100).
// The slider walks that list and the number box settles on the nearest entry when it loses
// focus, so the number shown is always one the dial actually does.
function nearestStep(steps, v) {
  return steps.reduce((best, s) => (Math.abs(s - v) < Math.abs(best - v) ? s : best), steps[0]);
}

export default function SettingField({ f, onChange }) {
  // Toggles were excluded here, so led_scan_mode and tray_battery could never be reset.
  const changed = f.default !== undefined && f.value !== f.default;
  const prov = PROVENANCE[f.provenance];
  const steps = Array.isArray(f.steps) && f.steps.length > 1 ? f.steps : null;
  // The number box keeps what you are typing to itself until you leave it (blur or Enter).
  // Committing on every keystroke had two faults: the clamp ran on the partial number, so
  // in a field with a minimum of 5 the "1" of "100" became 5 and the rest piled onto it;
  // and the Modules page saves and reloads on each change, which raced the next keystroke
  // and dropped it. One commit per edit: clamp to the range, snap to a step if there are
  // steps, then hand the value up once.
  const [draft, setDraft] = useState(null);
  const commitDraft = () => {
    if (draft === null) return;
    const n = Number(draft);
    setDraft(null);
    if (draft.trim() === "" || !Number.isFinite(n)) return;   // nothing typed: keep the value
    let v = Math.min(f.max, Math.max(f.min, n));
    if (steps) v = nearestStep(steps, v);
    if (v !== f.value) onChange(f.id, v);
  };
  // The slider, likewise, commits once: on release, not on every step of the drag. Each step
  // used to save (a request apiece, landing in any order) and, for Interface scaling, re-zoom the
  // whole page -- which moved the slider under the pointer and fired more steps. The value
  // stored was whichever request landed last, not the one let go on (owner, 2026-09-25).
  const [slide, setSlide] = useState(null);
  const commitSlide = () => {
    if (slide === null) return;
    setSlide(null);
    if (slide !== f.value) onChange(f.id, slide);
  };
  const slideEnd = { onPointerUp: commitSlide, onKeyUp: commitSlide, onBlur: commitSlide };
  // A setting that has no home yet in the browser dev build -- the system-tray battery needs the
  // Electron shell. Shown, but inert and labelled, rather than offering a switch that does nothing.
  if (f.deferred) {
    return (
      <SettingRow className="setting-deferred" label={f.label} desc={f.desc}
        badge={<Badge size="xs" title={f.deferred}>{f.deferred_badge || "desktop app"}</Badge>} />
    );
  }
  const resetLabel = f.kind === "toggle" ? (f.default ? "on" : "off") : `${f.default}${f.unit || ""}`;
  const control = f.kind === "toggle" ? (
    <Toggle checked={!!f.value} onChange={(v) => onChange(f.id, v)} label={f.label} />
  ) : f.kind === "select" ? (
    <select className="mac-input" value={f.value} onChange={(e) => onChange(f.id, e.target.value)}>
      {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  ) : (
    // A number box, because these ranges are unusable as a bare slider: idle_timeout_s
    // is 0-6000 across ~600px, so one pixel is ten seconds and the exact value you want
    // is unreachable by dragging.
    <input type="number" className="mac-input setting-num"
      min={f.min} max={f.max} value={draft ?? slide ?? f.value}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commitDraft}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
      title={steps ? `The dial can do: ${steps.join(", ")}` : undefined} />
  );
  return (
    <SettingRow
      label={f.label}
      badge={prov && <Badge size="xs" tone={prov.tone} title={prov.title}>{prov.label}</Badge>}
      control={control}
      desc={f.desc}
      changed={changed}
      onReset={() => onChange(f.id, f.default)}
      resetTitle={`Reset to ${resetLabel}`}
    >
      {f.kind === "slider" && steps && (
        <div className="setting-slider">
          <span className="setting-bound">{steps[0]}{f.unit}</span>
          <input
            type="range" min={0} max={steps.length - 1}
            value={steps.indexOf(nearestStep(steps, Number(slide ?? f.value)))}
            onChange={(e) => setSlide(steps[Number(e.target.value)])}
            {...slideEnd}
            title={`${slide ?? f.value} ticks per turn = one every ${(360 / Number(slide ?? f.value)).toFixed(1)} degrees`}
          />
          <span className="setting-bound">{steps[steps.length - 1]}{f.unit}</span>
        </div>
      )}
      {f.kind === "slider" && !steps && (
        <div className="setting-slider">
          <span className="setting-bound">{f.min}{f.unit}</span>
          <input
            type="range" min={f.min} max={f.max} value={slide ?? f.value}
            onChange={(e) => setSlide(Number(e.target.value))}
            {...slideEnd}
          />
          <span className="setting-bound">{f.max}{f.unit}</span>
        </div>
      )}
    </SettingRow>
  );
}
