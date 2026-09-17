import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useDeviceStream } from "../lib/deviceStream";
import { REPOS, checkRelease } from "../lib/updates";
import { notesFor } from "../changelog";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import { KVList, KVRow } from "../components/ui/KV";
import Notice from "../components/ui/Notice";

// The front door: the header, then the Create with one button into Bindings; beside it the
// backend, the keyboard on USB, what is new in this version with an opt-in release check,
// and the Create Companion, the host-side engine that pairs with this app.
export default function Hub() {
  const [sys, setSys] = useState(null);
  const [err, setErr] = useState(null);
  const [update, setUpdate] = useState(null);
  const { data: stream, connected } = useDeviceStream();
  const navigate = useNavigate();

  useEffect(() => {
    api.systemInfo().then(setSys).catch((e) => setErr(e.message));
  }, []);

  const halves = stream?.status?.halves || [];
  const version = sys?.backendVersion;
  const whatsNew = notesFor(version);
  // One line under the device name: what is on USB right now.
  const on = halves.filter((h) => h.connected);
  const modules = on.map((h) => h.module?.type).filter(Boolean);
  const deviceLine = on.length === 0
    ? "Not on USB"
    : (on.length === 2 ? "Both halves connected" : `${on[0].side === "left" ? "Left" : "Right"} half connected`)
      + (modules.length ? ` · ${modules.join(" and ")} docked` : "");

  return (
    <div className="hub">
      <header className="hub-head">
        <h1 className="hub-title">OpenFlow</h1>
        <p className="hub-sub">Open-Source Software for Naya Create: No cloud or external dependencies</p>
      </header>

      <div className="hub-body">
      {/* The device card: the name and what is connected at the top-left, the Create large
          and running off the card under a fade, the one button in at the bottom-left. */}
      <section className="hub-splash">
        <div className="hub-splash-head">
          <h2 className="hub-device">Naya Create</h2>
          <p className="hub-device-sub">{deviceLine}</p>
        </div>
        <img className="hub-splash-img" src="/brand/create-splash.png" alt="The Naya Create with a Touch and a Tune docked" />
        <Button variant="primary" className="hub-cta" onClick={() => navigate("/layer-management")}>
          Configure
        </Button>
      </section>

      <aside className="hub-side">
        <Card title="Backend">
          <div className="status">
            <span className={"dot " + (connected ? "ok" : "err")} />
            {connected ? "Connected" : "Offline"}
          </div>
          {sys && (
            <KVList>
              <KVRow k="Version" v={sys.backendVersion} />
              <KVRow k="OS" v={`${sys.os} ${sys.arch}`} />
            </KVList>
          )}
          {err && <Notice tone="err">{err}</Notice>}
        </Card>

        <Card title="Keyboard">
          {halves.length === 0 ? (
            <div className="hub-empty">No Naya Create on USB.</div>
          ) : (
            <KVList>
              {halves.map((h) => (
                <KVRow
                  key={h.side}
                  k={h.description || (h.side === "left" ? "Create Left" : "Create Right")}
                  mono={false}
                  v={h.connected
                    ? `${h.port ? h.port + " · " : ""}${h.batteryPercent != null ? h.batteryPercent + "%" : "connected"}${h.module ? " · " + h.module.type : ""}`
                    : "off"}
                />
              ))}
            </KVList>
          )}
        </Card>

        <Card title={whatsNew ? `What's new in ${whatsNew.version}` : "What's new"}>
          {whatsNew && (
            <ul className="hub-notes">
              {whatsNew.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
          <div className="hub-update">
            <Button size="sm" busy={!!update?.checking} onClick={() => checkRelease(REPOS.app, version, setUpdate)}>
              {update?.checking ? "Checking…" : "Check for updates"}
            </Button>
            {update?.error && <span className="hub-update-note err">{update.error}</span>}
            {update?.latest && (
              update.ahead
                ? <a className="hub-update-note" href={update.url} target="_blank" rel="noreferrer">{update.latest} is available ↗</a>
                : <span className="hub-update-note ok">Up to date{update.latest ? ` (${update.latest})` : ""}</span>
            )}
          </div>
        </Card>

        <Card title="Create Companion">
          <p className="hub-text">
            The host-side engine that turns the Create&apos;s F13 to F24 keys and module gestures into
            actions on this computer. Installed separately.
          </p>
          <a className="hub-link" href={`https://github.com/${REPOS.companion}/releases/latest`} target="_blank" rel="noreferrer">
            Latest release ↗
          </a>
        </Card>
      </aside>
      </div>
    </div>
  );
}
