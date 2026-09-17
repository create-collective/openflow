// Run a named action and keep its result (or failure) as text for an output box.
//
// Settings and Information each carried this verbatim: set busy, say what is running, show the
// JSON that came back or the error, clear busy. One copy now; the output box on either page
// reads `out` and `clear` empties it.
import { useCallback, useState } from "react";

export default function useRunLog() {
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (label, fn) => {
    setBusy(true);
    setOut(`${label}…`);
    try {
      const res = await fn();
      setOut(`${label}:\n${JSON.stringify(res, null, 2)}`);
      return res;
    } catch (e) {
      setOut(`${label} failed:\n${e.message}`);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);

  const clear = useCallback(() => setOut(""), []);

  return { out, busy, run, clear };
}
