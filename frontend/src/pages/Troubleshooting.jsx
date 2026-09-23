import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import BleSlots from "../components/BleSlots";
import { useShowAllKeyboards, visibleHalves } from "../lib/showAllKeyboards";
import useRunLog from "../lib/useRunLog";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Disclosure from "../components/ui/Disclosure";
import { KVRow } from "../components/ui/KV";
import Notice from "../components/ui/Notice";
import SettingRow from "../components/ui/SettingRow";
import Tabs from "../components/ui/Tabs";

// The page the nav calls "Information". It used to show none: three action buttons and a raw
// JSON dump, with every action hardcoded to the left half.
//
// It answers two questions, in that order of prominence. "Is it healthy?" -- specifically
// whether a half that seems missing is dead or merely no longer bonded to its partner, which
// look identical from outside and need opposite repairs. Then "what do I have?", per half and
// per module, with the firmware you run set against the firmware Naya ships.
//
// Layout note: the halves use a fixed two-column grid, not the shared .grid, whose auto-fill of
// 280px tracks left two narrow cards stranded in three empty columns on a wide window.

// Tabler Icons (MIT, Pawel Kuna): refresh, clock.
function Glyph({ name }) {
  const d = name === "refresh"
    ? "M20 11a8.1 8.1 0 0 0-15.5-2M4 5v4h4M4 13a8.1 8.1 0 0 0 15.5 2M20 19v-4h-4"
    : "M12 7v5l3 3";
  return (
    <svg className="info-glyph" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {name === "clock" && <circle cx="12" cy="12" r="9" />}
      <path d={d} />
    </svg>
  );
}

function KV({ k, v, mono = true, title }) {
  return <KVRow layout="grid" k={k} v={v} mono={mono} title={title} />;
}

// NayaFlow's own thresholds, so a battery reads the same here as in the app people came from.
function batteryTone(pct) {
  if (pct == null) return "";
  if (pct < 22) return "err";
  if (pct < 67) return "warn";
  return "ok";
}

function Battery({ pct, mv }) {
  if (pct == null) return null;
  return (
    <KVRow layout="grid" k="Battery" mono={false}>
      <span className="bat">
        <span className={"bat-fill " + batteryTone(pct)} style={{ width: `${pct}%` }} />
      </span>
      <span className="mono">{pct}%</span>
      {mv ? <span className="info-dim mono">{mv} mV</span> : null}
    </KVRow>
  );
}

// The verdict as a short pill; the sentence under it still says the whole thing.
const PAIRING = {
  paired: { tone: "ok", text: "Halves paired" },
  "half-paired": { tone: "warn", text: "One half only" },
  "not-paired": { tone: "err", text: "Not bonded" },
  incomplete: { tone: "warn", text: "Both halves needed" },
  unknown: { tone: "warn", text: "No pair address" },
};

// Halves grouped into the keyboards they belong to, with the firmware verdict for each.
// Exported so the verdict can be tested without the page: what it says about a keyboard whose
// halves disagree is the difference between "update it" and "it is broken".
export function buildBoards(halves) {
  const boards = [];
  for (const h of (halves || []).filter((x) => x.side !== "dongle")) {
    const id = h.keyboardId ?? 0;
    let b = boards.find((x) => x.id === id);
    if (!b) { b = { id, halves: [] }; boards.push(b); }
    b.halves.push(h);
  }
  for (const b of boards) {
    const fw = {};
    for (const h of b.halves) if (h.side === "left" || h.side === "right") fw[h.side] = h.firmwareVersion;
    b.fw = fw;
    // Both halves present, both reporting, and disagreeing. Not flagged when one is unknown:
    // "we could not read one of them" is a different statement from "they disagree".
    b.mismatch = !!(fw.left && fw.right && fw.left !== fw.right);
    // A half that answers with empty frames while its partner reads normally. This is the
    // shape a mismatch takes in practice, and the reason the check above could not see it:
    // the half that would prove the versions differ is the one that has stopped saying its
    // own (SCRUM-107).
    b.quiet = b.halves.find((h) => h.connected && h.reporting === false) || null;
    b.quietPartner = b.quiet
      ? b.halves.find((h) => h !== b.quiet && h.firmwareVersion) || null
      : null;
  }
  return boards;
}

function HalfCard({ h, reference, onIgnorePort, className = "" }) {
  const m = h.module;
  const behind = reference && h.firmwareVersion && h.firmwareVersion !== reference.createFirmware;
  const modBehind = reference && m?.firmwareVersion && m.firmwareVersion !== reference.moduleFirmware;
  return (
    <Card className={"info-card " + className} head={<span className={"dot " + (h.connected ? "ok" : "err")} />}
      title={h.description || h.side}
      actions={<Badge className="ui-badge-plain">{h.side === "dongle" ? "Dongle" : `${h.side[0].toUpperCase()}${h.side.slice(1)} half`}</Badge>}>
      {h.error && <Notice tone="err">{h.error}</Notice>}

      {/* The port opened, the commands were accepted, and every answer came back empty. The
          fields below would all be blank, which reads as a dead half -- and this one types
          normally. The cause we have measured is the two halves being on different firmware:
          the newer one reads perfectly and its partner's own port goes hollow (SCRUM-107). */}
      {h.reporting === false && (
        <Notice tone="warn" title="This half answers, but tells us nothing">
          Its port opened and accepted every command, and each reply came back empty — so
          firmware, battery and Bluetooth are all unreadable here. The half itself is fine and
          still types. The cause we have seen is the two halves running different firmware;
          putting both on the same version restores it.
        </Notice>
      )}

      {/* Only when the half could NOT be reached. A port that refused the handshake is
          not necessarily a ghost: on 3.28.7 every half exposes two CDC interfaces at once,
          permanently, and only one answers (SCRUM-90). The old copy asserted it was "left
          over from when it reconnected", which on that firmware is plainly untrue.

          The backend falls through to the sibling by itself now, so on a half we DID reach
          there is nothing for the user to do, and Ignore is worse than nothing: it persists
          to ignored-ports.json for good, and ignoring the interface that later becomes the
          answering one is how a half stops being found at all. When the half is connected
          this is reported as plain detail under Identity instead. */}
      {h.stalePorts?.length > 0 && !h.connected && (
        <Notice tone="warn" className="info-stale-port"
          title={`Also seen on ${h.stalePorts.join(", ")}`}
          action={onIgnorePort && (
            <Button size="sm" onClick={() => onIgnorePort(h.stalePorts[0])}>
              Ignore {h.stalePorts[0]}
            </Button>
          )}>
          This half did not answer. {h.stalePorts.length > 1 ? "These ports were" : "This port was"}
          {" "}tried and stayed silent; if {h.stalePorts.length > 1 ? "they are" : "it is"} a
          leftover from a reconnection, dropping {h.stalePorts.length > 1 ? "them" : "it"} from
          the list stops us trying {h.stalePorts.length > 1 ? "them" : "it"} again.
        </Notice>
      )}

      <div className="info-sub">Identity</div>
      <KV k="Firmware" v={h.firmwareVersion} />
      {behind && <div className="info-flag">Naya reference: {reference.createFirmware}</div>}
      <KV k="Hardware ID" v={h.hardwareId} />
      <KV k="USB product ID"
        v={h.pid != null ? `0x${h.pid.toString(16).toUpperCase().padStart(4, "0")}` : null}
        title="Identifies which half this is, and which firmware image it would take." />
      <KV k="Port" v={h.port} />
      {/* Named, not warned about: the half works, and which interface answered is the
          useful fact when someone is diagnosing one that does not. */}
      {h.connected && h.stalePorts?.length > 0 && (
        <KV k="Did not answer" v={h.stalePorts.join(", ")}
          title="This half exposes more than one serial interface. Only the port above answers; the others are left alone." />
      )}
      <Battery pct={h.batteryPercent} mv={h.batteryMillivolts} />

      {h.ble && (
        <>
          <div className="info-sub">Bluetooth</div>
          <KV k="Name" v={h.ble.name || "(unset)"} mono={false} />
          <KV k="Address" v={h.bleAddress} />
          <KV k="Paired to" v={h.ble.pairAddress}
            title="The address this half is bonded to. On a healthy pair this is the other half's address." />
          <KV k="Dongle" v={h.ble.dongleAddress} />
          <KV k="Radio firmware" v={h.ble.firmwareVersion} />
        </>
      )}

      <div className="info-sub">Docked module</div>
      {!m ? (
        <div className="info-empty">Nothing docked on this half.</div>
      ) : (
        <>
          <KV k="Type" v={m.type} mono={false} />
          <KV k="Firmware" v={m.firmwareVersion} />
          {modBehind && <div className="info-flag">Naya reference: {reference.moduleFirmware}</div>}
          <KV k="Address" v={m.address != null ? `0x${m.address.toString(16).toUpperCase()}` : null} />
          <Battery pct={m.batteryPercent} mv={m.batteryMillivolts} />
        </>
      )}
    </Card>
  );
}

export default function Troubleshooting() {
  const [halves, setHalves] = useState([]);
  // null = we cannot tell (no serial on one side or the other, real on older firmware).
  // false = the cached reading belongs to a keyboard that is not on USB now.
  const [describesAttached, setDescribesAttached] = useState(null);
  const [pairing, setPairing] = useState(null);
  const [recovery, setRecovery] = useState([]);
  const [sys, setSys] = useState(null);
  const [at, setAt] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [side, setSide] = useState("left");
  const { out, busy, run, clear } = useRunLog();
  const [live, setLive] = useState(false);   // read in this session, not restored from cache
  const [released, setReleased] = useState(false);
  const [ignored, setIgnored] = useState([]);
  const [now, setNow] = useState(() => Date.now());
  // Device | Connections | Troubleshooting. Device Manager's contents fold into these, so that
  // page leaves the nav (2026-09-11, owner). More tabs may come; these three are the spine.
  const [tab, setTab] = useState("device");

  // Tick so the age stays true while the page sits open, rather than freezing at whatever it
  // said on mount.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  // Hand the keyboard to another application, or take it back. Releasing closes the serial
  // ports and stands the poll down; nothing on the device changes either way.
  const toggleRelease = useCallback(async () => {
    setErr(null);
    try {
      const r = released ? await api.reconnectDevice() : await api.releaseDevice();
      setReleased(!!r.released);
    } catch (e) { setErr(e.message); }
  }, [released]);

  // Stop using a port, or take it back. Neither touches the device: an ignored port is
  // one we decline to choose, which is all anything can do about a node Windows keeps.
  // The screen is corrected in place rather than by re-reading the keyboard, which
  // would be a USB round trip for what is a decision about a list.
  const ignorePort = useCallback(async (port) => {
    setErr(null);
    try {
      const r = await api.ignorePort(port);
      setIgnored(r.ignored || []);
      setHalves((hs) => hs
        .filter((h) => h.port !== port)
        .map((h) => (h.stalePorts?.includes(port)
          ? { ...h, stalePorts: h.stalePorts.filter((p) => p !== port) }
          : h)));
    } catch (e) { setErr(e.message); }
  }, []);

  // Coming back is not instant: the port reappears on the next read, which the button
  // beside this says.
  const unignorePort = useCallback(async (port) => {
    setErr(null);
    try {
      const r = await api.unignorePort(port);
      setIgnored(r.ignored || []);
    } catch (e) { setErr(e.message); }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await api.statusDeep();
      setHalves(r.halves || []);
      setDescribesAttached(true);   // just read it; it is the attached board by definition
      setPairing(r.pairing || null);
      setRecovery(r.recovery || []);
      setAt(r.at ? new Date(r.at + "Z") : new Date());
      setLive(true);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, []);

  // System info is free (no USB), so it loads on mount. The device read is NOT, so the page
  // paints the last one from cache and only re-reads on a click -- the same bargain Device
  // Manager makes. Without this the page went blank every time you navigated away and back.
  useEffect(() => {
    let cancelled = false;
    api.systemInfo().then((r) => !cancelled && setSys(r)).catch(() => {});
    api.statusLast().then((r) => !cancelled && setReleased(!!r.released)).catch(() => {});
    api.devices().then((r) => !cancelled && setIgnored(r.ignored || [])).catch(() => {});
    (async () => {
      try {
        const last = await api.statusLastDeep();
        if (cancelled || !last?.halves?.length) return;
        setHalves(last.halves);
        setDescribesAttached(last.describesAttached ?? null);
        setPairing(last.pairing || null);
        setAt(last.at ? new Date(last.at + "Z") : null);
      } catch { /* nothing cached yet: the Read button is right there */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // Lighting controls, moved here from Device Manager. Restore is one layer-list write that
  // puts both halves back to the stored colours and animation; on/off are the plain LED
  // commands per half. All report into the output box like the diagnostics do.
  async function lighting(label, fn) {
    await run(label, fn);
  }

  // How old the reading is, shown rather than used to throw it away. Nothing here expires on a
  // clock: firmware, hardware ids and BLE addresses do not change while you look at them, and
  // blanking the page after N minutes would recreate the "it went empty" problem the cache was
  // added to fix. Battery and pairing DO drift, so the age is stated and goes amber once it is
  // old enough that a reading is worth repeating.
  const ageMs = at ? Math.max(0, now - at.getTime()) : null;
  const STALE_MS = 10 * 60 * 1000;
  const stale = ageMs != null && ageMs > STALE_MS;
  const ageText = ageMs == null ? null
    : ageMs < 60000 ? "just now"
    : ageMs < 3600000 ? `${Math.floor(ageMs / 60000)} min ago`
    : ageMs < 86400000 ? `${Math.floor(ageMs / 3600000)} h ago`
    : `${Math.floor(ageMs / 86400000)} d ago`;

  const connectedSides = halves.filter((h) => h.connected).map((h) => h.side);

  // Halves grouped into the keyboards they belong to. keyboardId is the backend's join by BLE
  // identity; the fallback of 0 keeps a single keyboard working if the field is ever absent.
  // A keyboard with nothing connected is dropped while another one IS connected: it has been
  // unplugged, and a ghost row helps nobody. The last keyboard standing always stays on screen
  // even when it goes, because "your keyboard is not answering" is the thing to show (SCRUM-86).
  const showAllKb = useShowAllKeyboards();
  const boards = buildBoards(visibleHalves(halves, showAllKb));
  const p = pairing && PAIRING[pairing.state];

  return (
    <div className="info-page">
      <div className="page-head info-head">
        <div>
          <h1 className="page-title">Device information</h1>
          <p className="page-sub">Hardware, connections, and diagnostics for your Create.</p>
        </div>
        <div className="btn-row">
          <Button onClick={toggleRelease} variant={released ? "primary" : "secondary"}
            title={released
              ? "Open the keyboard again so OpenFlow can read and flash it"
              : "Close the serial ports so NayaFlow or another application can use the keyboard"}>
            {released ? "Reconnect keyboard" : "Release keyboard"}
          </Button>
          <Button onClick={refresh} disabled={loading || released}>
            <Glyph name="refresh" />
            {loading ? "Reading…" : at ? "Read again" : "Read device info"}
          </Button>
        </div>
      </div>

      {/* The tabs, with how old the reading is at the other end of the same row: it belongs to
          every tab, not to the button that refreshes it. */}
      <div className="info-tabrow">
        <Tabs variant="segmented" className="info-tabs" ariaLabel="Information sections" value={tab} onChange={setTab}
          items={[{ id: "device", label: "Device" }, { id: "connections", label: "Connections" }, { id: "troubleshooting", label: "Troubleshooting" }]} />
        <span className={"info-age" + (stale ? " stale" : "")}>
          <Glyph name="clock" />
          {at
            ? `Last ${live ? "read" : "reading"} ${ageText}`
            : "Reads over USB. Nothing is written."}
        </span>
      </div>

      {ignored.length > 0 && (
        <Notice className="info-stale-port" title="Ignored ports"
          details={ignored.map((p) => (
            <div key={p} className="info-ignored-row">
              <span className="mono">{p}</span>
              <Button size="sm" onClick={() => unignorePort(p)}>Use it again</Button>
            </div>
          ))}
          detailsLabel={`${ignored.length} port${ignored.length === 1 ? "" : "s"}`}>
          OpenFlow is leaving these alone. Nothing on the keyboard changed; they are
          simply not offered as a way to reach it.
        </Notice>
      )}

      {released && (
        <Notice tone="warn" className="info-released" title="The keyboard is released"
          action={<Button onClick={toggleRelease}>Reconnect</Button>}>
          OpenFlow has closed the serial ports and stopped polling, so another application can
          use the keyboard. Nothing here can read or flash until you reconnect. What is shown
          below is the last reading.
        </Notice>
      )}

      {err && <Notice tone="err" className="info-released" onDismiss={() => setErr(null)}>{err}</Notice>}

      {tab === "device" && (
        <>
          {!at && !loading && (
            <Card className="info-blank" title="Nothing read yet">
              <div className="setting-desc">
                Press <strong>Read device info</strong> to ask both halves who they are. It is a
                read-only USB query — nothing is written to the keyboard.
              </div>
            </Card>
          )}
          {recovery.length > 0 && (
            <div className="info-banner warn">
              <div className="info-banner-title">
                Bootloader
                <Badge tone="warn">
                  {recovery.length} half{recovery.length === 1 ? "" : "s"} in recovery
                </Badge>
              </div>
              <div className="info-banner-detail">
                {recovery.map((r) => r.port).join(", ")} — a half in MCUboot answers none of the
                normal protocol, which is why it shows here rather than above.
              </div>
              <div className="info-banner-help">
                This is not damage. Every half passes through its bootloader for a second or two
                when it starts; this one has stayed, and a half that stays does not leave on its
                own. Switch it off and on again. If it comes straight back here, its firmware needs
                reinstalling.
              </div>
            </div>
          )}
          {/* A DIFFERENT keyboard, not merely an old reading. Everything below -- ports,
              serials, BLE addresses, docked modules -- belongs to hardware that is not on
              USB now. Kept rather than hidden: it is the last good reading, which is what
              someone chasing an intermittent board wants, and hiding it silently would be
              the same mistake in the other direction. Said plainly, with the fix offered. */}
          {describesAttached === false && halves.length > 0 && (
            <Notice size="sm" tone="err" className="info-stale-note"
              title="This describes a keyboard that is no longer connected"
              action={<Button size="sm" onClick={refresh} busy={loading}>Read the attached one</Button>}>
              It was read {ageText} from a different board, and nothing below has been
              re-checked since: the ports, serial numbers, addresses and modules are all that
              keyboard's. The bar at the top of the window is current.
            </Notice>
          )}
          {/* The keyboard this describes is not plugged in at all. Not a different board, so
              the wording is about absence rather than mistaken identity -- but a page listing
              ports and modules for hardware that is gone needs to say so either way. */}
          {describesAttached === "disconnected" && halves.length > 0 && (
            <Notice size="sm" tone="warn" className="info-stale-note"
              title="This keyboard is no longer connected"
              action={<Button size="sm" onClick={refresh} busy={loading}>Read again</Button>}>
              Everything below was read {ageText}, while it was plugged in. Nothing on USB
              answers to it now, so none of it has been re-checked.
            </Notice>
          )}
          {describesAttached !== false && describesAttached !== "disconnected" && stale && halves.length > 0 && (
            <Notice size="sm" tone="warn" className="info-stale-note">
              This reading is {ageText}. Firmware and addresses will not have changed, but battery
              and pairing may have — read again for those.
            </Notice>
          )}
          {/* One grid per physical KEYBOARD, not one grid of loose halves. With two Creates
              attached this used to fill left, left, right, right -- two lefts side by side on
              the top row -- because nothing said which halves belonged together. `keyboardId`
              comes from the backend, which joins them by BLE identity (SCRUM-86).

              The column is pinned by side rather than left to grid fill, so a keyboard whose
              right half is missing still draws its left on the left instead of sliding over. */}
          {boards.map((b, n) => (
            <div key={b.id}>
              {boards.length > 1 && (
                <div className="info-sub">
                  Keyboard {n + 1} of {boards.length}
                  {b.halves[0]?.serialNumber ? ` · ${b.halves[0].serialNumber}` : ""}
                </div>
              )}
              {b.mismatch && (
                <Notice tone="warn" title="This keyboard's halves are running different firmware">
                  The left half reports {b.fw.left} and the right reports {b.fw.right}. The halves
                  talk to each other over their own link, and a mismatch is known to break it, so
                  one half can stop responding while both still work over USB.
                </Notice>
              )}
              {/* Not "they disagree" -- one of them will not say. Worth its own banner, because
                  this is what a half-finished update looks like from the outside and the fix is
                  to finish it (SCRUM-107). */}
              {!b.mismatch && b.quiet && (
                <Notice tone="warn" title={`The ${b.quiet.side} half is not reporting`}>
                  It answers every command with an empty reply, so we cannot read its firmware
                  version{b.quietPartner
                    ? `, while the ${b.quietPartner.side} half reads normally on ${b.quietPartner.firmwareVersion}`
                    : ""}. That is what one half looks like when the two are on different
                  firmware — usually an update that only got as far as one of them. Both halves
                  on the same version puts it right; the half itself is not damaged.
                </Notice>
              )}
              <div className="info-halves">
                {b.halves.map((h) => (
                  <HalfCard key={h.port} h={h} reference={sys?.reference} onIgnorePort={ignorePort}
                    className={h.keyboardId == null ? ""
                      : h.side === "right" ? "info-col-right" : "info-col-left"} />
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {tab === "connections" && (
        <>
          {/* One banner per KEYBOARD. The verdict is a cross-comparison of one left against
              one right, so with two attached a single banner was judging halves that were
              never a pair (SCRUM-86). */}
          {(pairing?.keyboards?.length ? pairing.keyboards : pairing ? [pairing] : []).map((kb, n, all) => {
            const kp = PAIRING[kb.state];
            const board = boards.find((b) => b.id === kb.keyboardId);
            return (
            <div key={kb.keyboardId ?? n} className={"info-banner " + (kp ? kp.tone : "")}>
              <div className="info-banner-title">
                Split link
                {all.length > 1 && ` — keyboard ${n + 1}`}
                {all.length > 1 && board?.halves[0]?.serialNumber ? ` · ${board.halves[0].serialNumber}` : ""}
                {kp && <Badge className="ui-badge-plain" tone={kp.tone}>{kp.text}</Badge>}
              </div>
              <div className="info-banner-detail">{kb.detail}</div>
              {kb.state !== "paired" && kb.state !== "incomplete" && (
                <div className="info-banner-help">
                  Both halves are talking to this computer over USB, so neither is dead — they are
                  just not bonded to each other. Re-pairing is the repair here, not a firmware update.
                </div>
              )}
              {kb.state === "incomplete" && connectedSides.length > 0 && (
                <div className="info-banner-help">
                  Only the {connectedSides.join(" and ")} half answered over USB. Connect the missing
                  half directly with its own USB-C cable and read again — each half enumerates on its
                  own, so one can be reached even when the other cannot see it.
                </div>
              )}
              {board?.mismatch && (
                <div className="info-banner-help">
                  This keyboard&rsquo;s halves are on different firmware ({board.fw.left} and{" "}
                  {board.fw.right}), which is known to break the link between them even when the
                  bond itself is still recorded on both sides.
                </div>
              )}
            </div>
            );
          })}
          <div className="info-halves">
            {/* One card per KEYBOARD. It used to render a single card fed by the first left
                half it could find, so with two Creates attached the second one simply did not
                appear (SCRUM-86).

                Which of the five slots the keyboard sends to, and what each holds. A state of
                the keyboard, not a preference of the app, which is why it is here. Fed from
                the reading this page already holds, so the tab costs nothing to open and
                carries the same "as of" stamp and warnings as the Device tab (SCRUM-91). */}
            {boards.map((b, n) => (
              <Card key={b.id} className="info-card" ruled
                title={boards.length > 1 ? `Bluetooth slots — keyboard ${n + 1}` : "Bluetooth slots"}
                actions={boards.length > 1 && b.halves[0]?.serialNumber
                  ? <Badge className="ui-badge-plain">{b.halves[0].serialNumber}</Badge> : undefined}
                actionsAlign="end">
                <BleSlots half={b.halves.find((h) => h.side === "left") || b.halves[0]}
                  onRefresh={refresh} loading={loading} />
              </Card>
            ))}
            {halves.filter((h) => h.side === "dongle").length > 0
              ? halves.filter((h) => h.side === "dongle").map((h) => (
                  <HalfCard key={h.port} h={h} reference={sys?.reference} />
                ))
              : (
                <Card className="info-card" ruled title="Dongle"
                  actions={<Badge className="ui-badge-plain">Not on USB</Badge>} actionsAlign="end">
                  <Notice icon="info" title="Connect your dongle">
                    Plug it into USB, then read again to see its information.
                  </Notice>
                  <div className="info-sub">Firmware 3.07 limitation</div>
                  <div className="setting-desc">Wireless keyboard input is unavailable with this firmware.</div>
                  <Disclosure label="Technical details">
                    The dongle enumerates as its own serial device. Firmware 3.07 exposes no keyboard
                    interface, so it cannot bridge wireless keyboard input to this computer.
                  </Disclosure>
                </Card>
              )}
          </div>
        </>
      )}

      {tab === "troubleshooting" && (
        <>
          <div className="info-halves">
            <Card className="info-card" ruled title="Lighting">
              <div className="setting-desc" style={{ marginBottom: 10 }}>
                Restore puts both halves back to the profile's stored colors and animation after
                a lighting key changed them at runtime. On and off are the plain LED commands, per
                half.
              </div>
              <Button variant="primary" disabled={busy} className="info-lead-btn"
                onClick={() => lighting("Restore lighting", () => api.restoreLighting("left"))}>
                Restore lighting
              </Button>
              {["left", "right"].map((sd) => (
                <SettingRow key={sd} label={`${sd[0].toUpperCase()}${sd.slice(1)} half`}
                  control={
                    <span className="btn-row">
                      <Button size="sm" disabled={busy || (at != null && !connectedSides.includes(sd))}
                        onClick={() => lighting(`LEDs on (${sd})`, () => api.led(sd, "on"))}>
                        LEDs on
                      </Button>
                      <Button size="sm" disabled={busy || (at != null && !connectedSides.includes(sd))}
                        onClick={() => lighting(`LEDs off (${sd})`, () => api.led(sd, "off"))}>
                        LEDs off
                      </Button>
                    </span>
                  } />
              ))}
              <div className="setting-desc">On and off change the LEDs on that half.</div>
            </Card>
            <Card className="info-card" ruled title="Diagnostics"
              actions={<Badge className="ui-badge-plain">Read-only</Badge>} actionsAlign="end">
              <SettingRow bare className="info-runon" label="Run on"
                control={
                  <Tabs variant="segmented" ariaLabel="Half" value={side} onChange={setSide}
                    items={["left", "right", "dongle"].map((sd) => ({
                      id: sd, label: `${sd[0].toUpperCase()}${sd.slice(1)}`,
                      disabled: at != null && !connectedSides.includes(sd),
                      title: at != null && !connectedSides.includes(sd) ? "Not connected" : undefined,
                    }))} />
                } />
              <SettingRow label="Generate report" desc="Collect device information and diagnostics."
                control={<Button size="sm" disabled={busy}
                  onClick={() => run("Diagnostics report", api.diagnostics)}>Generate</Button>} />
              <SettingRow label="Dump settings" desc="Read the selected half's stored settings."
                control={<Button size="sm" disabled={busy}
                  onClick={() => run("Dump settings", () => api.dumpSettings(side))}>Read</Button>} />
              <SettingRow label="Test SPI flash" desc="Run the device's flash diagnostic."
                control={<Button size="sm" disabled={busy}
                  onClick={() => run("SPI flash self-test", () => api.sendCommand("repair_flash", [], { side }))}>Run test</Button>} />
              <div className="setting-desc info-runon-note">These checks do not change your bindings.</div>
              <Disclosure label="Recovery → Settings / Troubleshooting">
                Clearing Bluetooth bonds and wiping keymaps are managed in Settings &rsaquo;
                Troubleshooting, with a confirmation before data is erased.
              </Disclosure>
            </Card>
            <Card className="info-card info-span" ruled title="Software">
              <div className="info-software">
                <div>
                  <div className="info-sub info-sub-first">This computer</div>
                  <KV k="OpenFlow" v={sys?.backendVersion} />
                  <KV k="Operating system" v={sys ? `${sys.os} ${sys.osVersion}` : null} mono={false} />
                  <KV k="Architecture" v={sys?.arch} />
                  <KV k="Python" v={sys?.python} />
                </div>
                {sys?.reference && (
                  <div>
                    <div className="info-sub info-sub-first">Naya firmware reference</div>
                    <KV k="Create" v={sys.reference.createFirmware} />
                    <KV k="Module" v={sys.reference.moduleFirmware} />
                    <KV k="Source" v={sys.reference.source} mono={false} />
                  </div>
                )}
              </div>
            </Card>
          </div>
          {out && (
            <Card title="Output" actionsAlign="end" actions={<Button onClick={clear}>Clear</Button>}>
              <pre className="info-out">{out}</pre>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
