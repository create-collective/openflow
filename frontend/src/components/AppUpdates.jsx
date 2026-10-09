import { useEffect, useState } from "react";
import { REPOS, checkRelease } from "../lib/updates";
import Button from "./ui/Button";
import Notice from "./ui/Notice";
import Toggle from "./ui/Toggle";

// OpenFlow's own updates. In the desktop app the shell checks, downloads and installs
// (electron/updater.js, reached through the preload's window.openflowUpdates): nothing is checked
// until the user has answered once, then once a week, and an update installs only on a click,
// never while a flash runs. In a plain browser (the Vite dev server, the e2e tests) there is no
// shell, and the opt-in GitHub release check (lib/updates) stands in.
export const shellUpdates = typeof window !== "undefined" ? window.openflowUpdates || null : null;

/** The shell's update state, refreshed on demand; null outside the desktop app. */
export function useUpdateState() {
  const [state, setState] = useState(null);
  const refresh = () => shellUpdates?.state().then(setState).catch(() => {});
  useEffect(() => {
    refresh();
    // The weekly check found something while the app was open.
    const off = shellUpdates?.onAvailable(() => refresh());
    return () => off?.();
  }, []);
  return [state, refresh];
}

/** The once-only question, for the Hub. Renders nothing once it has been answered. */
export function AskAboutUpdates({ state, onAnswered, className }) {
  if (!shellUpdates || !state || state.check !== undefined) return null;
  const answer = (on) => shellUpdates.setCheck(on).then(onAnswered);
  return (
    <Notice className={className} title="Check for updates automatically, once a week?"
      action={<>
        <Button size="sm" variant="primary" onClick={() => answer(true)}>Yes</Button>
        <Button size="sm" onClick={() => answer(false)}>No</Button>
      </>}>
      OpenFlow would download one small file from GitHub that names the newest release. Nothing
      about you or your keyboard is sent, and nothing installs until you click Install. You can
      change this in Settings › About.
    </Notice>
  );
}

/**
 * Check now, the result, and Install. `compact` is the Hub's line; the full panel (Settings ›
 * About) adds the weekly switch and the release notes.
 */
export default function AppUpdates({ version, compact = false }) {
  const [state, refresh] = useUpdateState();
  const [result, setResult] = useState(null);   // { checking } | { error } | check result
  const [install, setInstall] = useState(null); // { percent } | { blocked } | { error } | { installing }

  useEffect(() => {
    const off = shellUpdates?.onProgress((p) => setInstall({ percent: p.percent }));
    return () => off?.();
  }, []);

  if (!shellUpdates) return <BrowserCheck version={version} compact={compact} />;

  const check = async () => {
    setResult({ checking: true });
    setInstall(null);
    const r = await shellUpdates.check().catch((e) => ({ error: e.message }));
    setResult(r);
    refresh();
  };
  const doInstall = async () => {
    setInstall({ percent: 0 });
    const r = await shellUpdates.install().catch((e) => ({ error: e.message }));
    setInstall(r);   // { installing } means the app is closing now
  };

  // A version is on offer from this check, or from the weekly one.
  const offered = result?.available ? result.latest : state?.known;
  const installing = install && ("percent" in install || install.installing);
  const busy = result?.checking || installing;

  return (
    <div className={compact ? "app-updates compact" : "app-updates"}>
      {!compact && state && (
        <Toggle variant="check" checked={state.check === true}
          onChange={(on) => shellUpdates.setCheck(on).then(refresh)}
          label="Check for updates automatically, once a week" />
      )}
      <div className="hub-update">
        {offered && state?.canInstall ? (
          <Button size="sm" variant="primary" busy={!!installing} disabled={!!installing} onClick={doInstall}>
            {installing ? installLabel(install) : `Install ${offered} and restart`}
          </Button>
        ) : (
          <Button size="sm" busy={!!result?.checking} disabled={busy} onClick={check}>
            {result?.checking ? "Checking…" : "Check for updates"}
          </Button>
        )}
        {offered && !state?.canInstall && state?.releasesUrl && (
          <a className="hub-update-note" href={state.releasesUrl} target="_blank" rel="noreferrer">
            Download {offered} ↗
          </a>
        )}
        {!offered && result && !result.checking && !result.error && (
          <span className="hub-update-note ok">Up to date{result.current ? ` (${result.current})` : ""}</span>
        )}
        {offered && state?.canInstall && !installing && (
          <span className="hub-update-note">{offered} is available</span>
        )}
      </div>
      {offered && !state?.canInstall && state?.unsupported && (
        <div className="page-sub">This copy is {state.unsupported}, which cannot replace itself.</div>
      )}
      {result?.error && <Notice tone="err" size="sm">Could not check: {result.error}</Notice>}
      {install?.blocked && <Notice tone="warn" size="sm">{install.blocked}</Notice>}
      {install?.error && <Notice tone="err" size="sm">The update did not install: {install.error}</Notice>}
      {install?.installing && (
        <div className="page-sub">OpenFlow closes to install {install.installing} and opens again by itself.</div>
      )}
      {!compact && result?.available && result.notes && <pre className="app-update-notes">{result.notes}</pre>}
    </div>
  );
}

function installLabel(install) {
  if (install.installing) return "Installing…";
  const pct = Math.round(install.percent || 0);
  return pct > 0 && pct < 100 ? `Downloading… ${pct}%` : "Preparing…";
}

// Outside the desktop app: the opt-in GitHub check, as before.
function BrowserCheck({ version, compact }) {
  const [update, setUpdate] = useState(null);
  return (
    <div className={compact ? "app-updates compact" : "app-updates"}>
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
    </div>
  );
}
