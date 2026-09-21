import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";
import Button from "./ui/Button";
import { KVRow } from "./ui/KV";
import Modal from "./ui/Modal";
import Notice from "./ui/Notice";

// Module firmware, kept deliberately apart from the keyboard's (owner, 2026-09-21).
//
// It is a different device, a different image and a different procedure, and none of it has been
// run. The keyboard path goes through MCUboot: upload to the secondary slot, verify the hash,
// swap on reset, with the primary image untouched until it succeeds. A module bundle is not an
// MCUboot image at all -- it is a LittleFS filesystem written into the left half's modules
// partition, with no slot to swap and nothing to roll back to. Sharing one button, or one
// dialog, between those two would be a promise the second one cannot keep.
//
// So this button exists and says what is true: the path is built, it is interlocked, and it has
// never been run on hardware. What it does NOT do is offer to run it. A greyed-out button with
// no explanation is the thing this app keeps having to fix, so the dialog explains where the
// work actually stands, shows what the docked modules are running, and points at the library
// for the bundles -- which can be downloaded today even though they cannot be written.

export default function ModuleFirmwareUpdate({ modules = [], reference }) {
  const [open, setOpen] = useState(false);
  const [library, setLibrary] = useState(null);

  const load = useCallback(async () => {
    try {
      setLibrary(await api.firmwareLibrary());
    } catch {
      setLibrary(null);
    }
  }, []);
  useEffect(() => { if (open) load(); }, [open, load]);

  const bundles = (library?.images || []).filter((i) => i.target === "module");
  const held = bundles.filter((i) => i.present).length;

  return (
    <>
      <Button onClick={() => setOpen(true)} title="What can be done with module firmware, and what cannot">
        Update module firmware…
      </Button>

      <Modal
        open={open}
        title="Module firmware"
        subtitle="A different device, a different procedure — and one that has not been run yet."
        onClose={() => setOpen(false)}
        width={560}
        footer={<Button variant="primary" onClick={() => setOpen(false)}>Close</Button>}
      >
        <Notice tone="warn" title="Writing module firmware is not enabled">
          The upload path is written and interlocked, and it has never been run on hardware. It
          stays switched off until it has been proven on a module someone is prepared to lose.
          <ul className="fw-expect">
            <li>
              A module bundle is a <strong>filesystem</strong>, not an MCUboot image. The keyboard
              flash writes to a spare slot and swaps only after the hash checks out, so a failure
              leaves the half exactly as it was. There is no spare slot here: an interrupted write
              leaves the modules partition partly erased.
            </li>
            <li>
              The keyboard itself is unaffected either way — it keeps working; module programming
              is what stops until a good bundle is written again.
            </li>
          </ul>
        </Notice>

        <h3 className="settings-section tight">What is docked</h3>
        {modules.length === 0
          ? <p className="page-sub">No module is docked. Dock one to read its firmware version.</p>
          : modules.map((m) => (
            <KVRow key={`${m.side}-${m.type}`} k={`${m.type} on the ${m.side} half`}
              v={m.firmwareVersion || "—"} />
          ))}
        {reference && <KVRow k="Naya ships (reference)" v={reference} />}

        <h3 className="settings-section tight">The bundles</h3>
        <p className="page-sub">
          {library
            ? `${held} of ${bundles.length} module bundle${bundles.length === 1 ? "" : "s"} `
              + "downloaded. They can be kept and inspected now — downloading a file is not "
              + "writing it to hardware — from the firmware library below."
            : "The firmware library below lists every module bundle OpenFlow has catalogued."}
        </p>
      </Modal>
    </>
  );
}
