import { useState } from "react";
import { invalidateDeviceState, setModuleRead } from "../lib/deviceState";
import useDoneFlag from "../lib/useDoneFlag";
import { api } from "../lib/api.js";
import { getActiveProfileId } from "../lib/activeProfile";
import { hasReadDevice } from "../lib/deviceActions";
import { useDeviceStream } from "../lib/deviceStream";
import { getShowAllKeyboards, visibleHalves } from "../lib/showAllKeyboards";
import { targetSerialFor } from "../lib/targetKeyboard";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import Notice from "./ui/Notice";

// "Flash to keyboard" — previews the diff (dry-run) first, then requires an explicit
// confirm. Confirm performs the real write: the backend takes a fresh device read first
// (needed to preserve the module->dock bindings the app does not model), checks every
// frame's ack, and verifies by reading the device back. The pre-flash read comes back in
// the result as a backup.

// The active profile (lib/activeProfile, shared with every page). A flash MUST name one: the
// layers table spans every profile, so an unscoped plan would write whichever one the DB
// happened to return last. If nothing is selected we send nothing and let the backend refuse
// by name, better than guessing which keymap goes on the keyboard. The read gate
// (hasReadDevice) lives with the read itself in lib/deviceActions.
function activeProfileId() {
  return getActiveProfileId() || undefined;
}

// Recovery flash: skips the pre-flash read, writes everything, and cannot verify afterwards,
// so it overwrites what the app does not model -- module-to-dock assignments, transparent keys
// and second-bank (double-tap / tap+hold) bindings. It is the right tool for a board that can
// no longer be read and the wrong thing to click by accident, so it is not offered while the
// beta build is out (owner, 2026-09-17). Flip this to bring the button back; the backend path
// is untouched and still demands acknowledgeRecovery.
const RECOVERY_OFFERED = false;

// One glyph per kind of thing a flash writes (Tabler Icons, MIT, Pawel Kuna: stack, palette,
// list, cpu, clock).
const FLASH_GLYPH = {
  layers: <><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5M3 17l9 5 9-5" /></>,
  palette: <><circle cx="12" cy="12" r="9" /><circle cx="8.5" cy="10" r="1" /><circle cx="12" cy="7.5" r="1" /><circle cx="15.5" cy="10" r="1" /><path d="M12 21a2.5 2.5 0 0 1 0-5a2 2 0 0 0 0-4" /></>,
  list: <path d="M4 6h16M4 12h16M4 18h10" />,
  chip: <><rect x="7" y="7" width="10" height="10" rx="1.5" /><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>,
};
function FlashGlyph({ name }) {
  return (
    <svg className="flash-glyph" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {FLASH_GLYPH[name]}
    </svg>
  );
}

function summarize(ops) {
  const g = { layers: 0, colors: 0, modules: 0, timeouts: 0, layerList: 0, wipes: 0 };
  for (const op of ops || []) {
    const l = op.label || "";
    // Order matters: "layer list: 0, 1, 2" and "wipe layer 3" both start with words that the
    // looser checks below would swallow. Counting the layer-list op as a layer is what made a
    // three-layer profile report "4 layers".
    if (l.startsWith("layer list")) g.layerList++;
    else if (l.startsWith("wipe")) g.wipes++;
    else if (l.startsWith("layer")) g.layers++;
    else if (l.startsWith("led")) g.colors++;
    else if (l.startsWith("module")) g.modules++;
    else if (l.startsWith("timeout")) g.timeouts++;
  }
  return g;
}

export default function FlashButton({ disabled = false, disabledTitle }) {
  const [state, setState] = useState("idle"); // idle | loading | preview | writing | done | error
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [wrote, setWrote] = useState(false);   // did this attempt reach the device?
  const { data } = useDeviceStream();

  // Which keyboard to write to, when more than one is attached. A flash goes to the LEFT half,
  // so that is the half named. Null with a single keyboard, and the backend then has nothing to
  // disambiguate; with several and no target it refuses rather than writing to whichever ranked
  // first, which is how a flash lands on the wrong board (SCRUM-86).
  const targetBody = () => {
    const s = targetSerialFor(
      visibleHalves(data?.status?.halves || [], getShowAllKeyboards()), "left");
    return s ? { target: s } : {};
  };
  // Bindings the plan could not encode. Declared here because it was NOT: setDropped was called
  // in the flash handler and `dropped` read in the result panel, with no useState between them,
  // so every real flash threw "setDropped is not defined" AFTER the device had already been
  // written. The write succeeded and the UI reported a failure -- the worst way round.
  // tools/check-undefined.mjs only looks at hooks and components, which is why it passed.
  const [dropped, setDropped] = useState([]);
  const readOk = hasReadDevice();
  // Bays the first layer leaves unset. Layer 0 is where a module profile is pulled to both
  // sides and every other layer inherits from; a gap there leaves that module unconfigured on
  // the keyboard, so Confirm is off until it is filled (the route refuses it too).
  const bayGaps = preview?.baseBayGaps || [];
  const bayGapName = (loc) => {
    const [type, side] = loc.split(":");
    return `${type.charAt(0).toUpperCase() + type.slice(1)}, ${(side || "").replace("keyboard_", "")} bay`;
  };

  // The dialog reports the result, but it gets closed. A flash is slow, irreversible and easy
  // to be unsure about, so the button carries the answer for a few seconds afterwards too.
  const [flashed, markFlashed] = useDoneFlag();

  async function openPreview() {
    setState("loading");
    setError("");
    setWrote(false);
    try {
      const res = await api.flashPreview({ profileId: activeProfileId(), ...targetBody() });
      setPreview(res);
      setState("preview");
    } catch (e) {
      setError(e.message || String(e));
      setState("error");
    }
  }

  async function confirmFlash() {
    setState("writing");
    setError("");
    setWrote(true);
    try {
      // Whatever we believed was on the device is now stale, whether this succeeds or not.
      invalidateDeviceState("flash");
      const res = await api.flash(
        recovery
          ? { mode: "recovery", acknowledgeRecovery: true, profileId: activeProfileId(),
              ...targetBody() }
          : { full: false, profileId: activeProfileId(), collectOrphans: true, ...targetBody() });
      setResult(res);
      // The flash reads the modules back on success, so publish that rather than making the
      // user read again to see the result of a write we just checked. If the follow-up read
      // failed the state stays invalidated, which is the honest fallback.
      if (res.moduleState?.modules) {
        const byUuid = {};
        for (const m of res.moduleState.modules) if (m?.uuid) byUuid[m.uuid] = m;
        setModuleRead(byUuid);
      }
      // "verified" = every ack was good AND the read-back matched. Anything else is a
      // problem the user needs to see, not a success with a caveat.
      // A verified flash is not necessarily a complete one: verification only checks records
      // the plan actually SET, so a binding we could not encode passes unnoticed. Keep them.
      setDropped(res.dropped || []);
      setState(res.status === "verified" ? "done" : "error");
      if (res.status === "verified") markFlashed();
      if (res.status !== "verified") {
        // Say WHICH write failed: the op label, its frame and the ack flag are the only facts
        // that let anyone reason about a mid-flash abort afterwards (2026-09-16 the message
        // alone left it unknowable whether slot 1 or slot 6 had been refused).
        const where = res.op != null
          ? ` (at "${res.op}", frame ${res.frame ?? "?"}, ack ${res.ack_flags == null ? "none" : "0x" + Number(res.ack_flags).toString(16)})`
          : "";
        setError((res.reason || `flash finished as "${res.status}" — check the device`) + where);
      }
    } catch (e) {
      setError(e.message || String(e));
      setState("error");
    }
  }

  function close() {
    setState("idle");
    setPreview(null);
    setResult(null);
    setError("");
    setWrote(false);
  }

  const s = preview?.summary;
  const g = s ? summarize(s.ops) : null;

  const footer = (
    <>
      <Button onClick={close} disabled={state === "writing"}>
        {state === "done" ? "Close" : "Cancel"}
      </Button>
      {RECOVERY_OFFERED && state !== "done" && !readOk && !recovery && (
        <Button
          onClick={() => setRecovery(true)}
          title="For a keyboard that can no longer be read. Overwrites everything."
        >
          Can't read the board?
        </Button>
      )}
      {state !== "done" && (
        <Button
          variant="primary"
          onClick={confirmFlash}
          disabled={state === "writing" || (!readOk && !recovery) || bayGaps.length > 0}
          title={
            bayGaps.length > 0
              ? "Layer 0 leaves a module bay unset; fill it on the Bindings board first"
              : recovery
              ? "Overwrites the keyboard without reading it first"
              : readOk
              ? "Writes this profile to the keyboard, then reads it back to verify"
              : "Read the keyboard first"
          }
        >
          {state === "writing"
            ? "Writing…"
            : recovery
            ? "Recovery flash (overwrites everything)"
            : "Confirm flash"}
        </Button>
      )}
    </>
  );

  return (
    <>
      <Button
        variant="primary"
        done={flashed && !disabled}
        onClick={openPreview}
        disabled={disabled || state === "loading" || state === "writing"}
        title={
          disabled
            ? disabledTitle
            : flashed
            ? "Flashed and verified"
            : "Preview the changes, then confirm to write them to the keyboard"
        }
      >
        {state === "loading"
          ? "Previewing…"
          : state === "writing"
          ? "Flashing…"
          : flashed
          ? "✓ Flashed"
          : "⚡ Flash to keyboard"}
      </Button>

      {/* Kept open through "writing" and "done". It used to render for preview|error only, so
          confirming unmounted the whole dialog mid-write: the "do not unplug it" note and the
          verified summary below were unreachable, and a flash finished with no signal at all.
          Not dismissable while a write is in flight -- there is nothing to go back to, and the
          click would only hide the one thing worth watching. */}
      <Modal
        open={state !== "idle" && state !== "loading"}
        title={state === "writing" ? "Flashing…" : state === "done" ? "Flashed ✓" : "Flash to keyboard"}
        subtitle={state === "preview" ? "Preview only — nothing is written until you confirm." : undefined}
        onClose={close}
        dismissable={state !== "writing"}
        footer={footer}
      >
        {state === "error" && (
          <Notice tone="err" title={wrote ? "Flash failed" : "Preview failed"}>{error}</Notice>
        )}

        {(state === "preview" || state === "writing") && s && (
          <>
            {/* What the flash will write, one row per kind, as storyboard view 09 draws it. */}
            <ul className="flash-diff">
              <li><FlashGlyph name="layers" /><span><b>{g.layers}</b> layer{g.layers === 1 ? "" : "s"}</span></li>
              <li><FlashGlyph name="palette" /><span><b>{g.colors}</b> colour map{g.colors === 1 ? "" : "s"}</span></li>
              {g.layerList > 0 && (
                <li title="Tells the keyboard which layer is which. Written only when the board disagrees.">
                  <FlashGlyph name="list" /><span>Layer list</span>
                </li>
              )}
              {g.wipes > 0 && (
                <li><FlashGlyph name="list" /><span><b>{g.wipes}</b> deleted-layer wipe{g.wipes === 1 ? "" : "s"}</span></li>
              )}
              {g.modules > 0 && (
                <li><FlashGlyph name="chip" /><span><b>{g.modules}</b> module config{g.modules === 1 ? "" : "s"}</span></li>
              )}
              {/* A full module store is garbage-collected as far as needed: a slot holding a
                  profile this keyboard profile does not reference is written over. Said out
                  loud, because the profile it held is gone from the board afterwards. */}
              {preview?.modules?.reclaimed?.length > 0 && (
                <li title="No free module slot was left, so a slot holding a module profile this keyboard profile does not use is written over.">
                  <FlashGlyph name="chip" />
                  <span>Reusing {preview.modules.reclaimed.map((r) => `slot ${r.slot} (was ${r.was})`).join(", ")}</span>
                </li>
              )}
              {g.timeouts > 0 && <li><FlashGlyph name="clock" /><span>Timeouts</span></li>}
            </ul>
            <div className="flash-diff-tot">
              {s.total_frames} frames · {s.total_bytes} bytes → {s.dest}
            </div>
            <details className="ui-disclosure flash-ops">
              <summary className="ui-disclosure-summary">Write plan ({s.ops.length} ops)</summary>
              <table>
                <tbody>
                  {s.ops.map((op, i) => (
                    <tr key={i}>
                      <td>{op.label}</td>
                      <td className="mono">{op.sub}</td>
                      <td>{op.payload_bytes} B</td>
                      <td>{op.frames} fr</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        )}

        {/* Bindings the encoder cannot express. Shown BEFORE writing, because the whole
            failure this fixes was finding out never. The key is left alone rather than
            cleared -- clearing would destroy a binding the user did not ask to remove. */}
        {state === "preview" && preview?.dropped?.length > 0 && (
          <Notice tone="warn" className="flash-dropped">
            <strong>
              {preview.dropped.length} binding{preview.dropped.length === 1 ? "" : "s"} cannot
              be written to the keyboard
            </strong>
            <ul>
              {preview.dropped.slice(0, 6).map((d, i) => (
                <li key={i}>
                  <code>{d.actionCode || d.actionType}</code> on layer {d.layer}, key{" "}
                  {d.position} — {d.reason}
                </li>
              ))}
            </ul>
            {preview.dropped.length > 6 && <div>…and {preview.dropped.length - 6} more.</div>}
            <div>Everything else in this flash is unaffected; those keys keep what they have.</div>
          </Notice>
        )}

        {/* Module slots the board carries that this profile does not reference. Removed on every
            flash since 2026-09-26, as NayaFlow does: as an opt-in box, testers left it unticked
            and every stale slot kept reading back (and being captured) as a profile. Listed here
            so the removal is never silent; warn tone because it is permanent. */}
        {state === "preview" && preview?.orphans?.length > 0 && (
          <Notice tone="warn" icon={null} className="flash-orphans">
            <strong>
              Removes {preview.orphans.length} unused module slot{preview.orphans.length === 1 ? "" : "s"}
            </strong>
            <div className="flash-orphans-detail">
              {preview.orphans.map((o) => `Slot ${o.slot}${o.name ? ` (${o.name})` : ""}`).join(", ")}
              {preview.orphans.length === 1 ? " is" : " are"}
              {" on the keyboard but not used by this profile, so this flash removes "}
              {preview.orphans.length === 1 ? "it" : "them"}
              {" from the keyboard. Your saved module profiles are not affected."}
            </div>
          </Notice>
        )}

        {state === "preview" && bayGaps.length > 0 && (
          <Notice tone="warn" className="flash-dropped">
            <strong>
              Layer 0 leaves {bayGaps.length} module bay{bayGaps.length === 1 ? "" : "s"} unset:{" "}
              {bayGaps.map(bayGapName).join(", ")}
            </strong>
            <div>
              The first layer must choose a profile (or "disabled") for every module type on
              both sides; the other layers inherit it. A module with nothing on layer 0 runs
              unconfigured. Pick one on the Bindings board, then preview again.
            </div>
          </Notice>
        )}

        {!readOk && !recovery && (
          <Notice>
            Read the keyboard first (Bindings → Read from keyboard). Flashing without it
            would write over a state the app has not seen.
          </Notice>
        )}
        {recovery && (
          <Notice>
            <strong>Recovery flash.</strong> The board is not read first, so nothing can be
            preserved: module-to-dock assignments, transparent keys and double-tap bindings
            are all overwritten. Only use this if the keyboard cannot be read.
          </Notice>
        )}
        {state === "writing" && (
          <Notice>
            <span className="flash-spinner" aria-hidden="true" />
            Writing to the keyboard, then reading it back to verify — do not unplug it.
          </Notice>
        )}
        {state === "done" && result && (
          <Notice tone={dropped.length ? "warn" : "ok"} className={dropped.length ? "flash-dropped" : ""}>
            <strong>Flashed and verified.</strong> {result.ops} operation(s),{" "}
            {result.frames} frame(s), read back with no differences.
            {/* Verification only checks records the plan SET, so it passes even when a
                binding could not be encoded. Saying "verified" and stopping there is what
                made this class of bug invisible for so long. */}
            {dropped.length > 0 && (
              <>
                <div style={{ marginTop: 8 }}>
                  <strong>
                    But {dropped.length} binding{dropped.length === 1 ? "" : "s"} could not be
                    written.
                  </strong>{" "}
                  Those keys keep what the keyboard already had on them.
                </div>
                <ul>
                  {dropped.slice(0, 6).map((d, i) => (
                    <li key={i}>
                      <code>{d.actionCode || d.actionType}</code> on layer {d.layer}, key{" "}
                      {d.position} — {d.reason}
                    </li>
                  ))}
                </ul>
                {dropped.length > 6 && <div>…and {dropped.length - 6} more.</div>}
              </>
            )}
          </Notice>
        )}

      </Modal>
    </>
  );
}
