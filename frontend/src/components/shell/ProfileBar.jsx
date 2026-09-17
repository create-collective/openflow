import { useEffect } from "react";
import { api } from "../../lib/api";
import { backupNow, clearDeviceError, readKeyboard, useDeviceActions } from "../../lib/deviceActions";
import { hydrateDeviceState, invalidateDeviceState } from "../../lib/deviceState";
import { useDeviceStream } from "../../lib/deviceStream";
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
export default function ProfileBar() {
  const ed = useProfileEditor();
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

  return (
    <div className="shell-bar" role="region" aria-label="Keyboard profile and actions">
      <div className="shell-bar-profile">
        {ed.profile ? (
          <ProfileMenu profiles={ed.profiles} activeProfileId={ed.profile.id} {...ed.profileHandlers} />
        ) : (
          <span className="shell-bar-empty">{ed.loaded ? "No profiles" : "Loading…"}</span>
        )}
      </div>

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

      {/* Between the status and the buttons, in space that is there whether or not there is a
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

      <div className="shell-bar-actions">
        <Button
          size="sm"
          variant="primary"
          done={dev.justRead}
          onClick={readKeyboard}
          disabled={!!dev.busy}
          title="Read the map currently on the connected keyboard into a profile"
        >
          {dev.busy === "read" ? "Reading…" : dev.justRead ? "✓ Read" : "⌨  Read from keyboard"}
        </Button>
        <Button
          size="sm"
          onClick={backupNow}
          disabled={!!dev.busy}
          title="Snapshot everything to a backup file. Edits are saved as you make them; this keeps a restore point."
        >
          {dev.busy === "save" ? "Backing up…" : "⭳  Back up"}
        </Button>
        <FlashButton />
      </div>
    </div>
  );
}
