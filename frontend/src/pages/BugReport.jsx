import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Disclosure from "../components/ui/Disclosure";
import Notice from "../components/ui/Notice";
import Toggle from "../components/ui/Toggle";

// Report a problem. The backend assembles the report (it can see the version, the Python it
// runs on and the device log, which the renderer cannot) and owns where it goes; this page
// collects the words, shows EXACTLY what will travel with them, and offers the text back when
// there is nowhere to send it. No credential ships with OpenFlow, so a build with no sink
// configured lands on the copy / save path rather than pretending to file something.
const FIELDS = [
  { id: "happened", label: "What happened", required: true, rows: 4,
    placeholder: "What you did, and what the app or the keyboard did." },
  { id: "expected", label: "What you expected", rows: 2,
    placeholder: "What you thought would happen instead." },
  { id: "steps", label: "Steps to reproduce", rows: 4,
    placeholder: "1. Open Bindings\n2. Select a key\n3. …" },
];

export default function BugReport() {
  const { pathname } = useLocation();
  const [form, setForm] = useState({ title: "", happened: "", expected: "", steps: "", contact: "" });
  const [identifiers, setIdentifiers] = useState(false);
  const [context, setContext] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  // Reloaded when the identifier switch moves, so the preview is always the thing that would
  // actually be sent rather than a sample of it.
  const load = useCallback(() => {
    api.reportContext(identifiers).then(setContext).catch((e) => setErr(e.message));
  }, [identifiers]);
  useEffect(() => { load(); }, [load]);

  const set = (id) => (e) => setForm((f) => ({ ...f, [id]: e.target.value }));
  const ready = form.happened.trim().length > 0;
  const sink = context?.sink;

  async function send() {
    setBusy(true);
    setErr("");
    try {
      // `page` is where the user was BEFORE opening this form, which is the useful one; the
      // form's own route never is.
      const r = await api.reportBug({ ...form, includeIdentifiers: identifiers,
                                      page: sessionStorage.getItem("openflow.lastPage") || pathname });
      setResult(r);
      if (!r.ok && r.configured) setErr(r.reason || "the report could not be filed");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function copyReport() {
    const text = result?.description;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setErr("Could not reach the clipboard. Use Save report instead.");
    }
  }

  function saveReport() {
    const text = result?.description;
    if (!text) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `openflow-report-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function again() {
    setResult(null);
    setForm({ title: "", happened: "", expected: "", steps: "", contact: "" });
  }

  return (
    <div className="report-page">
      <div className="page-head report-head">
        <div>
          <h1 className="page-title">
            Report a problem
            {sink === null && <Badge className="ui-badge-plain" title="No tracker is configured in this build, so the report is yours to send.">Copy or save</Badge>}
          </h1>
          <p className="page-sub">Tell us what went wrong. The report carries what OpenFlow knows about this machine.</p>
        </div>
      </div>

      {err && <Notice tone="err" className="report-notice" onDismiss={() => setErr("")}>{err}</Notice>}

      {result?.ok ? (
        <Notice tone="ok" className="report-notice" title="Report filed"
          action={result.url
            ? <Button onClick={() => window.open(result.url, "_blank", "noreferrer")}>Open {result.key}</Button>
            : undefined}>
          Thank you. It is logged as {result.key || "a new item"} and will be read.
          {result.note ? ` (${result.note})` : ""}
          <div className="report-again"><Button onClick={again}>Report something else</Button></div>
        </Notice>
      ) : result ? (
        <Notice tone="warn" className="report-notice"
          title={result.configured ? "The report could not be filed" : "This build has no tracker configured"}
          details={<pre className="report-text">{result.description}</pre>}
          detailsLabel="Show the report">
          Your report is written up and ready. Copy it or save it, and send it on however suits.
          <div className="report-again">
            <Button variant="primary" onClick={copyReport} done={copied}>
              {copied ? "✓ Copied" : "Copy report"}
            </Button>
            <Button onClick={saveReport}>Save report</Button>
            <Button onClick={again}>Start over</Button>
          </div>
        </Notice>
      ) : null}

      {!result && (
        <>
          <Card className="report-card" title="What went wrong">
            <label className="report-field">
              <span className="report-label">Title</span>
              <input className="mac-input report-input" value={form.title} onChange={set("title")}
                placeholder="One line: what is broken" />
            </label>
            {FIELDS.map((f) => (
              <label className="report-field" key={f.id}>
                <span className="report-label">
                  {f.label}
                  {f.required && <span className="report-req" title="Required"> *</span>}
                </span>
                <textarea className="mac-input report-input" rows={f.rows}
                  value={form[f.id]} onChange={set(f.id)} placeholder={f.placeholder} />
              </label>
            ))}
            <label className="report-field">
              <span className="report-label">How to reach you (optional)</span>
              <input className="mac-input report-input" value={form.contact} onChange={set("contact")}
                placeholder="Email or GitHub handle, if you want a reply" />
            </label>
          </Card>

          <Card className="report-card" title="What will be sent">
            <p className="settings-card-desc">
              Your words above, plus the version you are running, this computer&rsquo;s operating
              system, the keyboard OpenFlow last saw, and the most recent device
              communication. Nothing is sent until you press Send report.
            </p>
            <Toggle variant="check" checked={identifiers} onChange={setIdentifiers}
              label="Include hardware identifiers" />
            <p className="report-ids">
              Hardware IDs, Bluetooth addresses and USB serial numbers name your particular
              keyboard. They are removed unless you turn this on, which is worth doing only for a
              problem that looks specific to one unit.
            </p>
            <Disclosure label="Show the exact data">
              <pre className="report-text">{context ? JSON.stringify(context, null, 1) : "Loading…"}</pre>
            </Disclosure>
          </Card>

          <div className="report-actions">
            <Button variant="primary" onClick={send} busy={busy} disabled={!ready || busy}
              title={ready ? undefined : "Say what happened first"}>
              {busy ? "Sending…" : "Send report"}
            </Button>
            <span className="report-hint">
              {sink ? "Goes straight to the OpenFlow tracker."
                : "No tracker is configured here, so you will be given the report to send."}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
