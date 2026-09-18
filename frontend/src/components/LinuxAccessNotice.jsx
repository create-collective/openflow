import { useState } from "react";
import Button from "./ui/Button";
import Notice from "./ui/Notice";

// Linux without OpenFlow's udev rule: the halves show up on USB but their serial ports will not
// open, because they belong to root and the dialout group. The backend recognises that refusal
// (device/port_access.py) and attaches the fix to the half's status; this shows it once, however
// many halves it applies to, with the commands to paste. The .deb installs the rule itself, so
// this is mostly for the AppImage.
export function accessFix(halves) {
  return (halves || []).find((h) => h.fix?.kind === "linux-udev-rule")?.fix || null;
}

export default function LinuxAccessNotice({ fix, className = "" }) {
  const [copied, setCopied] = useState(false);
  const [copyErr, setCopyErr] = useState(null);
  if (!fix) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(fix.commands);
      setCopyErr(null);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyErr("Could not reach the clipboard. Select the commands and copy them instead.");
    }
  }

  return (
    <Notice
      tone="warn"
      className={className}
      title="Linux is not letting OpenFlow open the keyboard"
      action={<Button size="sm" onClick={copy}>{copied ? "Copied" : "Copy commands"}</Button>}
    >
      <p className="access-fix-text">
        Run these once in a terminal. They install OpenFlow&apos;s udev rule, which lets you use
        the keyboard without root and keeps ModemManager from probing it.
      </p>
      <pre className="access-fix-cmd">{fix.commands}</pre>
      <p className="access-fix-text">
        If the keyboard still shows as off afterwards, unplug it and plug it back in.
      </p>
      {copyErr && <p className="access-fix-text err">{copyErr}</p>}
    </Notice>
  );
}
