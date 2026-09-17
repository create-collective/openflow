// The two whole-keyboard actions a page offers beside Flash: read it, and back the data up.
//
// They lived in Bindings.jsx, which is why only that page could read the keyboard. The
// persistent profile bar offers them everywhere, so they live here; a page passes `onRead` for
// what it does with the result (reload its profiles, switch to the profile the read produced,
// repaint the bays).
import { useCallback, useState } from "react";
import { api } from "./api";
import { setModuleRead } from "./deviceState";
import useDoneFlag from "./useDoneFlag";

// Has the keyboard been read in this app session? Flashing is gated on it: until the board has
// been read, the app's idea of the keymap may not match what is on the keyboard, and edits
// would be flashed over an unknown state. sessionStorage, so it lasts the window, not the machine.
const READ_KEY = "openflow.deviceRead";
export function hasReadDevice() {
  try {
    return Boolean(sessionStorage.getItem(READ_KEY));
  } catch {
    return false;
  }
}

export default function useDeviceActions({ onRead } = {}) {
  const [busy, setBusy] = useState(null);       // "read" | "save" | null
  const [err, setErr] = useState(null);
  const [readNote, setReadNote] = useState(null);
  const [saved, setSaved] = useState(null);
  const [justRead, markRead] = useDoneFlag();

  const readKeyboard = useCallback(async () => {
    setBusy("read");
    setErr(null);
    setReadNote(null);
    try {
      const r = await api.readKeyboard();
      if (onRead) await onRead(r);
      // A read is a read wherever it was started from: publish the module configs the board
      // carries into the shared device state, so the Modules page shows the on-device marks
      // without having to read again.
      if (r.modules) {
        const byUuid = {};
        for (const m of r.modules) byUuid[m.uuid] = m;
        setModuleRead(byUuid);
      }
      try { sessionStorage.setItem(READ_KEY, String(Date.now())); } catch { /* ignore */ }
      // A read that worked used to say nothing at all, so the only way to tell it apart from
      // a read that silently failed was to go looking at the data.
      markRead();
      setReadNote({
        at: new Date(),
        text: `${r.bindings} binding(s) across ${r.layers} layer(s)`,
        warnings: r.warnings?.length || 0,
      });
      return r;
    } catch (e) {
      const noDev = /device|found|503|connect/i.test(e.message);
      setErr(noDev ? "No keyboard found. Connect the Create over USB and close NayaFlow." : e.message);
      return null;
    } finally {
      setBusy(null);
    }
  }, [onRead, markRead]);

  const backupNow = useCallback(async () => {
    setBusy("save");
    setErr(null);
    try {
      await api.createBackup();
      setSaved(new Date());
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }, []);

  // An edit means the map is no longer "backed up" until Back up is pressed again.
  const clearSaved = useCallback(() => setSaved(null), []);

  return { busy, err, setErr, readNote, saved, clearSaved, justRead, readKeyboard, backupNow };
}
