import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useDeviceStream } from "../lib/deviceStream";
import { KNOWLEDGE_BASE_URL, ORG, REPOS } from "../lib/updates";
import { notesFor } from "../changelog";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import { KVList, KVRow } from "../components/ui/KV";
import Notice from "../components/ui/Notice";
import LinuxAccessNotice, { accessFix } from "../components/LinuxAccessNotice";
import AppUpdates, { AskAboutUpdates, useUpdateState } from "../components/AppUpdates";

// The front door: the header, then the Create with one button into Bindings; beside it the
// backend, the keyboard on USB, what is new in this version with OpenFlow's own updates (and,
// once only, the question whether to look for them weekly), and the Create Companion, the
// host-side engine that pairs with this app.
export default function Hub() {
  const [sys, setSys] = useState(null);
  const [err, setErr] = useState(null);
  const [updates, refreshUpdates] = useUpdateState();
  const { data: stream, connected } = useDeviceStream();
  const navigate = useNavigate();

  useEffect(() => {
    api.systemInfo().then(setSys).catch((e) => setErr(e.message));
  }, []);

  const halves = stream?.status?.halves || [];
  // Linux without the udev rule: on USB, but the ports will not open (LinuxAccessNotice).
  const fix = accessFix(halves);
  const version = sys?.backendVersion;
  const whatsNew = notesFor(version);
  // One line under the device name: what is on USB right now.
  const on = halves.filter((h) => h.connected);
  const modules = on.map((h) => h.module?.type).filter(Boolean);
  const deviceLine = on.length === 0
    ? (fix ? "On USB, but Linux will not let OpenFlow open it" : "Not on USB")
    : (on.length === 2 ? "Both halves connected" : `${on[0].side === "left" ? "Left" : "Right"} half connected`)
      + (modules.length ? ` · ${modules.join(" and ")} docked` : "");

  return (
    <div className="hub">
      <header className="hub-head">
        <h1 className="hub-title">Welcome to OpenFlow</h1>
        <p className="hub-sub">Open-Source Software for Naya Create: No cloud or external dependencies</p>
      </header>

      <LinuxAccessNotice fix={fix} className="hub-access" />
      <AskAboutUpdates state={updates} onAnswered={refreshUpdates} className="hub-ask-updates" />

      <div className="hub-body">
        <div className="hub-col">
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

          <div className="hub-row">
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
                        : (h.fix ? "no permission" : "off")}
                    />
                  ))}
                </KVList>
              )}
            </Card>

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
          </div>
        </div>

        <div className="hub-col">
          <Card title={whatsNew ? `What's new in ${whatsNew.version}` : "What's new"}>
            {whatsNew && (
              <ul className="hub-notes">
                {whatsNew.notes.map((n) => <li key={n}>{n}</li>)}
              </ul>
            )}
            <AppUpdates version={version} compact />
          </Card>

          <h2 className="hub-section">Other Software and Resources for the Create</h2>
          {/* The create-collective organization first, then what it publishes: the knowledge base,
              then its software. nayactl is Cory Bennett's, not the org's, so it comes last. */}
          <Card title="create-collective GitHub">
            <p className="hub-text">
              The community organization behind OpenFlow, Create Companion and the knowledge base:
              every project's source, releases and issues.
            </p>
            <a className="hub-link" href={`https://github.com/${ORG}`} target="_blank" rel="noreferrer">
              create-collective on GitHub ↗
            </a>
          </Card>
          <Card title="Create Knowledge Base">
            <p className="hub-text">
              The open knowledge base for the Naya Create: hardware, protocol, firmware, recovery
              and host software.
            </p>
            <a className="hub-link" href={KNOWLEDGE_BASE_URL} target="_blank" rel="noreferrer">
              Open the knowledge base ↗
            </a>
          </Card>
          <Card title="Create Companion">
            <p className="hub-text">
              The host-side engine that turns the Create&apos;s module gestures into dynamic, profiled
              keybindings for the application you are working in. Installed separately.
            </p>
            <a className="hub-link" href={`https://github.com/${REPOS.companion}/releases/latest`} target="_blank" rel="noreferrer">
              Latest release ↗
            </a>
          </Card>

          <Card title="nayactl">
            <p className="hub-text">
              Command-line communication with the Naya Create, by Cory Bennett. OpenFlow talks to
              the keyboard through nayactl: it is built on this project and ships a copy of it
              under the Apache 2.0 license.
            </p>
            <a className="hub-link" href={`https://github.com/${REPOS.nayactl}`} target="_blank" rel="noreferrer">
              nayactl on GitHub ↗
            </a>
          </Card>
        </div>
      </div>
    </div>
  );
}
