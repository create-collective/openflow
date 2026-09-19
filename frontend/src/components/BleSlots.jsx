import { useState } from "react";
import { api } from "../lib/api";
import { confirmDialog } from "../lib/dialogs";
import Button from "./ui/Button";
import { KVRow } from "./ui/KV";
import Notice from "./ui/Notice";

// The keyboard's five Bluetooth slots. Slot 0 is never offered by NayaFlow's keys and is most
// likely the dongle's, so it is shown but not selectable. Select does what pressing BT n on the
// keyboard does; Clear does what BT_CLEAR does to the selected slot. Both are confirmed.
//
// Painted from the half the PAGE already read, not from a read of its own (SCRUM-91). This used
// to fire a live USB read on every navigation to the tab, while the Device tab beside it painted
// from cache and re-read on an explicit click -- so Connections paid the cost, and took any
// failure, every single time it was opened. Sharing the page's reading means one cost, one "as
// of" stamp, and one set of warnings about a reading that describes a keyboard which is no
// longer attached.
export default function BleSlots({ half, onRefresh, loading = false }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const ble = half?.ble || null;
  const side = half?.side || "left";
  // Only false when the half was asked and could not answer. Absent means nothing asked yet.
  const unavailable = ble != null && ble.slotsAvailable === false;
  const slots = ble?.slots || [];

  async function act(label, fn) {
    setBusy(true);
    setErr("");
    try {
      const r = await fn();
      if (r && r.ok === false) setErr(`${label}: ${r.note || "the keyboard did not confirm it"}`);
      // A slot change is a change to the keyboard, so the page's reading is now out of date.
      if (onRefresh) await onRefresh();
    } catch (e) {
      setErr(`${label}: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function select(i) {
    const ok = await confirmDialog({
      title: `Switch the keyboard to Bluetooth slot ${i}?`,
      message: `This is the same as pressing BT ${i} on the keyboard: typing moves to whatever is paired in that slot. If nothing is paired there, typing stops until you press USB-C on the keyboard or power cycle it.`,
      confirmLabel: "Switch",
    });
    if (!ok) return;
    act(`Select slot ${i}`, () => api.selectBleProfile(side, i));
  }

  async function clear(i) {
    const ok = await confirmDialog({
      title: `Clear Bluetooth slot ${i} and start pairing?`,
      message: `Whatever is paired in slot ${i} is forgotten. The keyboard then advertises so a new host can pair to it.`,
      confirmLabel: "Clear and pair",
      tone: "danger",
    });
    if (!ok) return;
    act(`Clear slot ${i}`, () => api.clearBleProfile(side, i));
  }

  const working = busy || loading;

  return (
    <div>
      <div className="btn-row" style={{ alignItems: "center", marginBottom: 8 }}>
        <Button onClick={onRefresh} busy={loading}>
          {loading ? "Reading…" : "Read from keyboard"}
        </Button>
        {ble?.activeProfile != null && (
          <span className="saved-note ok">Active slot: {ble.activeProfile}</span>
        )}
      </div>
      {err && <Notice tone="err">{err}</Notice>}

      {/* No reading yet. Says so, rather than reaching for the keyboard on its own. */}
      {!ble && (
        <div className="empty">
          Nothing read yet. Press Read from keyboard to ask it about its Bluetooth slots.
        </div>
      )}

      {/* The half answered, but its firmware has no BLE_GET_STATUS, so which slot is active and
          which hold a bond is genuinely unknowable (SCRUM-91). This used to be an error and a
          blank panel. A limitation gets a quiet notice, and what the keyboard DID tell us is
          worth showing: it is most of what this panel is for. */}
      {unavailable && (
        <>
          <Notice title="Bluetooth slots need newer firmware">
            This keyboard&rsquo;s firmware does not report Bluetooth slot status, so which slot is
            active and which are paired cannot be shown. Everything below was read from the
            keyboard normally.
          </Notice>
          <KVRow k="This half's address" v={half?.bleAddress || "unknown"} />
          {ble?.name && <KVRow k="Name" v={ble.name} />}
          <KVRow k="Paired with" v={ble?.pairAddress || "nothing"} />
        </>
      )}

      {slots.map((s) => (
        <KVRow key={s.index} style={{ alignItems: "center" }}
          k={s.reserved ? "Slot 0 — reserved (dongle)" : `Slot ${s.index} (BT ${s.index})`}>
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span title={[
              s.active ? "The keyboard sends to this slot when on wireless output." : null,
              s.connected ? "The paired host is connected right now." : s.bonded ? "A host is paired here." : "Nothing is paired here.",
              s.peerAddress ? `Host: ${s.peerAddress}` : null,
            ].filter(Boolean).join("\n")}>
              {(s.active ? "● Active" : "") + (s.connected ? (s.active ? ", connected" : "Connected") : s.bonded ? (s.active ? ", paired" : "Paired") : s.active ? "" : "Empty")}
            </span>
            {!s.reserved && (
              <>
                <Button disabled={working || s.active} onClick={() => select(s.index)}
                  title="Same as pressing this BT key on the keyboard.">Select</Button>
                <Button disabled={working} onClick={() => clear(s.index)}
                  title="Forget the host paired here and start pairing mode for this slot.">Clear &amp; pair</Button>
              </>
            )}
          </span>
        </KVRow>
      ))}

      <Notice style={{ marginTop: 8 }}>
        Read from the {side} half over USB, as part of the reading this page shows. The keyboard
        keeps the active slot across power cycles.
      </Notice>
    </div>
  );
}
