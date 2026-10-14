import { useState } from "react";
import { api } from "../lib/api";
import Button from "./ui/Button";
import Notice from "./ui/Notice";

// "Check what it runs", on the Information page's bootloader banner: asks a half that is sitting
// in MCUboot which firmware images it holds and names each against the catalogue, the read
// tools/naya-probe.py does from a terminal. Reads only (/api/recovery-read): two SMP reads, the
// port closed after. Bringing the half OUT of the bootloader is a write and stays off in this
// build (owner, 2026-10-09); a power cycle does that.
export default function BootloaderCheck() {
  const [read, setRead] = useState(null);   // { busy } | { error } | the endpoint's answer

  const check = async () => {
    setRead({ busy: true });
    try { setRead(await api.recoveryRead()); } catch (e) { setRead({ error: e.message }); }
  };

  return (
    <div className="bootloader-check">
      <Button size="sm" busy={!!read?.busy} onClick={check}>
        {read && !read.busy ? "Check again" : "Check what it runs"}
      </Button>
      {read?.error && <Notice tone="err" size="sm">Could not read it: {read.error}</Notice>}
      {read?.state === "none" && (
        <Notice size="sm">No half is in the bootloader now. It may have restarted on its own; press Read device info.</Notice>
      )}
      {read?.state === "error" && <Notice tone="warn" size="sm">{read.detail}</Notice>}
      {read?.state === "ok" && (
        <div className="bootloader-check-result">
          <div className="setting-desc">
            {read.port}
            {read.pidSide ? `, a ${read.pidSide} half` : ""} holds {read.images.length} firmware
            image{read.images.length === 1 ? "" : "s"}:
          </div>
          <ul>
            {read.images.map((img) => (
              <li key={`${img.slot}-${img.hash}`}>
                Slot {img.slot}: {img.identified ? describe(img) : `version ${img.version || "unknown"}, an image OpenFlow does not hold`}
                {img.active ? " · running" : ""}
                {img.confirmed ? " · confirmed" : ""}
              </li>
            ))}
          </ul>
          <div className="setting-desc">
            If the half keeps coming back here after a power cycle, include this in a bug report.
          </div>
        </div>
      )}
    </div>
  );
}

function describe(img) {
  const side = img.side ? `${img.side[0].toUpperCase()}${img.side.slice(1)}` : "";
  return `Create ${side} ${img.versionLabel || img.version || ""}`.replace(/\s+/g, " ").trim();
}
