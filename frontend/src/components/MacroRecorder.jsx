import { useCallback, useEffect, useRef, useState } from "react";
import { chordFromEvent } from "../lib/recordkeys";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import Card from "./ui/Card";
import Notice from "./ui/Notice";
import Toggle from "./ui/Toggle";

// Record a macro by typing it, instead of adding steps one at a time.
//
// Capture happens in the page, not on the keyboard: the firmware has no macro table (see
// db/macros.py), so there is nothing on the device to record from. That is a real limitation
// and it is stated in the UI rather than glossed -- the browser only sees what the OS hands it,
// so anything the OS eats first (Win+L, Alt+Tab, Ctrl+Alt+Del, PrintScreen) cannot be recorded.
//
// Gaps between keys are measured and become each step's delay, because a macro typed at human
// speed and replayed with a flat 30 ms is a different macro. The first key has no preceding gap,
// so it takes the floor.
export default function MacroRecorder({ onCommit, onCancel }) {
  const [recording, setRecording] = useState(false);
  const [events, setEvents] = useState([]);
  const [keepTiming, setKeepTiming] = useState(true);
  const last = useRef(null);

  const stop = useCallback(() => setRecording(false), []);

  useEffect(() => {
    if (!recording) return undefined;
    function onKeyDown(e) {
      // Escape ends the recording rather than being recorded -- otherwise there is no way to
      // stop without the mouse, and a stray Escape is the likeliest thing to want undone.
      if (e.key === "Escape") {
        e.preventDefault();
        stop();
        return;
      }
      const chord = chordFromEvent(e);
      if (!chord) return;              // a bare modifier: wait for the key it modifies
      e.preventDefault();
      e.stopPropagation();
      const now = performance.now();
      const gap = last.current == null ? 0 : Math.round(now - last.current);
      last.current = now;
      setEvents((prev) => [...prev, { ...chord, gap }]);
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [recording, stop]);

  function start() {
    setEvents([]);
    last.current = null;
    setRecording(true);
  }

  const steps = events.map((ev, i) => ({
    kind: "key",
    actionCode: ev.actionCode,
    state: "tap",
    // Clamp so a pause while thinking does not become a 40-second step.
    delay: !keepTiming ? 30 : i === 0 ? 30 : Math.min(5000, Math.max(0, ev.gap)),
  }));

  return (
    <Card className="macro-record"
      title={<>Record{recording && <Badge tone="err" style={{ marginLeft: 8 }}>recording</Badge>}</>}>

      {!recording && events.length === 0 && (
        <div className="setting-desc" style={{ marginBottom: 10 }}>
          Press Record, then type the sequence. Escape stops. Keys your operating system handles
          first — Win+L, Alt+Tab, Ctrl+Alt+Del, PrintScreen — never reach the browser and cannot
          be captured; add those with the key picker instead.
        </div>
      )}

      {recording && (
        <Notice style={{ marginBottom: 10 }}>
          Recording. Every keystroke is captured — press <strong>Escape</strong> to stop.
        </Notice>
      )}

      {events.length > 0 && (
        <div className="rec-strip">
          {events.map((ev, i) => (
            <span key={i} className="rec-chip">
              {ev.label}
              {keepTiming && i > 0 && <span className="rec-gap">{Math.min(5000, ev.gap)}ms</span>}
            </span>
          ))}
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 12, alignItems: "center" }}>
        {!recording ? (
          <Button variant="primary" onClick={start}>
            {events.length ? "Record again" : "Record"}
          </Button>
        ) : (
          <Button onClick={stop}>Stop</Button>
        )}
        {events.length > 0 && !recording && (
          <>
            <Toggle variant="check" checked={keepTiming} onChange={setKeepTiming} label="Keep my timing" />
            <Button variant="primary" onClick={() => onCommit(steps)}>
              Add {steps.length} step{steps.length === 1 ? "" : "s"}
            </Button>
            <Button onClick={() => { setEvents([]); onCancel?.(); }}>Discard</Button>
          </>
        )}
      </div>
    </Card>
  );
}
