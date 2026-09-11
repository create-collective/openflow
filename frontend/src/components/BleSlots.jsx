import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

// The keyboard's five Bluetooth slots, read from the left half's status. Slot 0 is never
// offered by NayaFlow's keys and is most likely the dongle's, so it is shown but not
// selectable. Select does what pressing BT n on the keyboard does; Clear does what BT_CLEAR
// does to the selected slot. Both are confirmed, both re-read the status afterwards.
export default function BleSlots({ side = "left" }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      setData(await api.bleProfiles(side));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }, [side]);

  useEffect(() => { load(); }, [load]);

  async function act(label, fn) {
    setBusy(true);
    setErr("");
    try {
      const r = await fn();
      if (r && r.ok === false) setErr(`${label}: ${r.note || "the keyboard did not confirm it"}`);
      await load();
    } catch (e) {
      setErr(`${label}: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  function select(i) {
    if (!confirm(`Switch the keyboard to Bluetooth slot ${i}?\n\nThis is the same as pressing BT ${i} on the keyboard: typing moves to whatever is paired in that slot. If nothing is paired there, typing stops until you press USB-C on the keyboard or power cycle it.`)) return;
    act(`Select slot ${i}`, () => api.selectBleProfile(side, i));
  }

  function clear(i) {
    if (!confirm(`Clear Bluetooth slot ${i} and start pairing?\n\nWhatever is paired in slot ${i} is forgotten. The keyboard then advertises so a new host can pair to it.`)) return;
    act(`Clear slot ${i}`, () => api.clearBleProfile(side, i));
  }

  return (
    <div>
      <div className="btn-row" style={{ alignItems: "center", marginBottom: 8 }}>
        <button className="btn" onClick={load} disabled={busy}>{busy ? "Reading…" : "Refresh"}</button>
        {data && <span className="saved-note ok">Active slot: {data.activeProfile}</span>}
      </div>
      {err && <div className="error">{err}</div>}
      {!data && !err && <div className="empty">Reading Bluetooth status…</div>}
      {data && (data.slots || []).map((s) => (
        <div className="kv" key={s.index} style={{ alignItems: "center" }}>
          <span className="k">
            {s.reserved ? "Slot 0 — reserved (dongle)" : `Slot ${s.index} (BT ${s.index})`}
          </span>
          <span className="v" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span title={[
              s.active ? "The keyboard sends to this slot when on wireless output." : null,
              s.connected ? "The paired host is connected right now." : s.bonded ? "A host is paired here." : "Nothing is paired here.",
              s.peerAddress ? `Host: ${s.peerAddress}` : null,
            ].filter(Boolean).join("\n")}>
              {(s.active ? "● Active" : "") + (s.connected ? (s.active ? ", connected" : "Connected") : s.bonded ? (s.active ? ", paired" : "Paired") : s.active ? "" : "Empty")}
            </span>
            {!s.reserved && (
              <>
                <button className="btn" disabled={busy || s.active} onClick={() => select(s.index)}
                  title="Same as pressing this BT key on the keyboard.">Select</button>
                <button className="btn" disabled={busy} onClick={() => clear(s.index)}
                  title="Forget the host paired here and start pairing mode for this slot.">Clear &amp; pair</button>
              </>
            )}
          </span>
        </div>
      ))}
      <div className="phase-note" style={{ marginTop: 8 }}>
        Read from the left half over USB. The keyboard keeps the active slot across power cycles.
      </div>
    </div>
  );
}
