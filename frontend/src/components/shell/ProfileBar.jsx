import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { backupNow, clearDeviceError, readKeyboard, useDeviceActions } from "../../lib/deviceActions";
import { hydrateDeviceState, invalidateDeviceState } from "../../lib/deviceState";
import { useDeviceStream } from "../../lib/deviceStream";
import { keyboardChoices, setTargetKeyboard, targetSerialFor, useTargetKeyboard }
  from "../../lib/targetKeyboard";
import useProfileEditor from "../../lib/useProfileEditor";
import DeviceChip from "../DeviceChip";
import FlashButton from "../FlashButton";
import ProfileMenu from "../ProfileMenu";
import Button from "../ui/Button";
import IconButton from "../ui/IconButton";

// The persistent bar under the nav: the active keyboard profile, one status box per half, the
// read / back-up notes, and the three whole-keyboard actions. On every page, so reading the
// keyboard and flashing it no longer depend on which page happens to be open. The profile
// menu drives the shared active profile (lib/activeProfile), which every page follows.
// Flashing writes the whole profile, so it is offered from the pages that edit what gets
// written -- Bindings, LED Map and Modules -- and disabled elsewhere with a note saying where
// to go. Macros is deliberately not one of them: macros never reach the keyboard.
const FLASH_ROUTES = ["/layer-management", "/colormapping", "/module-configuration"];

export default function ProfileBar() {
  const ed = useProfileEditor();
  const { pathname } = useLocation();
  const canFlash = FLASH_ROUTES.includes(pathname);
  const { data, connected } = useDeviceStream();
  const dev = useDeviceActions();

  // If we lose the backend we can no longer vouch for what is on the keyboard.
  useEffect(() => {
    if (!connected) invalidateDeviceState("disconnected");
  }, [connected]);
  // Seed from the last read the backend recorded, so a reload does not drop the live marks.
  // It is a belief with a timestamp, not a claim about the board right now -- see deviceState.
  useEffect(() => { hydrateDeviceState(api); }, []);

  const err = dev.err || ed.error;

  // With one keyboard there is nothing to choose and nothing is shown. With several, the
  // backend refuses to guess which to read or flash, so the choice has to be made here
  // (SCRUM-86). Default to the first so the actions are never dead, but say which it is.
  const halves = data?.status?.halves || [];
  const choices = halves.length > 2 ? keyboardChoices(halves) : [];
  const target = useTargetKeyboard();
  useEffect(() => {
    if (!choices.length) return;
    if (!choices.some((c) => c.serial && c.serial === target)) {
      setTargetKeyboard(choices[0].serial);   // the chosen board was unplugged, or none yet
    }
  }, [choices.map((c) => c.serial).join(","), target]);

  return (
    <div className="shell-bar" role="region" aria-label="Keyboard profile and actions">
      <div className="shell-bar-profile">
        {ed.profile ? (
          <ProfileMenu profiles={ed.profiles} activeProfileId={ed.profile.id} {...ed.profileHandlers} />
        ) : (
          <span className="shell-bar-empty">{ed.loaded ? "No profiles" : "Loading…"}</span>
        )}
      </div>

      {/* Between the profile and the halves, in space that is there whether or not there is a
          note, so nothing moves when one arrives. */}
      <div className="shell-bar-notes">
        {err ? (
          <span className="saved-note err">
            {err}
            <IconButton plain size="sm" title="Dismiss" onClick={() => { clearDeviceError(); ed.setErr(null); }}>✕</IconButton>
          </span>
        ) : (
          <>
            {dev.readNote && (
              <span className={"saved-note" + (dev.readNote.warnings ? "" : " ok")}>
                Read {dev.readNote.at.toLocaleTimeString()} — {dev.readNote.text}
                {dev.readNote.warnings > 0 && ` · ${dev.readNote.warnings} key(s) need review (BT/LED/other)`}
              </span>
            )}
            {dev.saved && <span className="saved-note">Backed up {dev.saved.toLocaleTimeString()}</span>}
          </>
        )}
      </div>

      {choices.length > 1 && (
        <div className="shell-bar-target" title="Which keyboard Read and Flash act on">
          <label htmlFor="target-keyboard">Acting on</label>
          <select id="target-keyboard" value={target || ""}
            onChange={(e) => setTargetKeyboard(e.target.value)}>
            {choices.map((c) => (
              <option key={c.id} value={c.serial || ""}>
                {c.label}{c.firmware ? ` · ${c.firmware}` : ""}{c.serial ? ` · ${c.serial.slice(-6)}` : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="shell-bar-status">
        {connected ? (
          <DeviceChip status={data?.status} />
        ) : (
          <span className="shell-bar-offline" title="The backend is not answering">
            <span className="dot err" />
            Backend offline
          </span>
        )}
      </div>

      <div className="shell-bar-actions">
        <Button
          variant="primary"
          done={dev.justRead}
          onClick={() => readKeyboard(targetSerialFor(halves, "left"))}
          disabled={!!dev.busy}
          title="Read the map currently on the connected keyboard into a profile"
        >
          {dev.busy === "read" ? "Reading…" : dev.justRead ? "✓ Read" : "⌨  Read from keyboard"}
        </Button>
        <Button
          onClick={backupNow}
          disabled={!!dev.busy}
          title="Snapshot everything to a backup file. Edits are saved as you make them; this keeps a restore point."
        >
          {dev.busy === "save" ? "Backing up…" : "⭳  Back up"}
        </Button>
        <FlashButton
          disabled={!canFlash}
          disabledTitle="Open Bindings, LED Map or Modules to flash this profile"
        />
      </div>
    </div>
  );
}
