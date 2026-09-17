import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { formatCombo } from "../lib/combo";
import Button from "./ui/Button";

// Per-application shortcuts: 5,311 chords across 20 applications.
//
// This has its own component rather than living in the palette's category grid, because the
// shape of the problem is different. A grid of 44px buttons works for 26 letters; for five
// thousand entries the only usable interface is choose-an-app, then search. It also fetches its
// own data: the file is 1.2 MB, so it must not ride along on the action catalog that every page
// loads.
//
// Platform matters here in a way it does not elsewhere. The same action is a different chord on
// Windows and macOS -- Ctrl+C against Cmd+C -- so the toggle changes what would be BOUND, not
// just what is displayed, which is the opposite of the virtual keyboard's Mac checkbox.
export default function AppShortcutPicker({ disabled, onPick, disabledHint }) {
  const [apps, setApps] = useState([]);
  const [app, setApp] = useState("");
  const [platform, setPlatform] = useState("windows");
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let dead = false;
    api.appShortcuts().then((r) => {
      if (dead) return;
      setApps(r.apps || []);
      // Land on something rather than an empty pane: the first app is as good a default as any,
      // and an empty list with a dropdown reads as broken.
      if (!app && r.apps?.length) setApp(r.apps[0].name);
    }).catch((e) => !dead && setErr(e.message));
    return () => { dead = true; };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!app) return;
    let dead = false;
    setBusy(true);
    // Debounced: typing "render" is six keystrokes and six round trips otherwise.
    const t = setTimeout(() => {
      api.appShortcuts({ app, platform, q, limit: 300 })
        .then((r) => { if (!dead) { setRes(r); setErr(""); } })
        .catch((e) => !dead && setErr(e.message))
        .finally(() => !dead && setBusy(false));
    }, q ? 180 : 0);
    return () => { dead = true; clearTimeout(t); };
  }, [app, platform, q]);

  const grouped = useMemo(() => {
    const by = new Map();
    for (const a of apps) {
      const c = a.category || "Other";
      if (!by.has(c)) by.set(c, []);
      by.get(c).push(a);
    }
    return [...by.entries()].sort((x, y) => x[0].localeCompare(y[0]));
  }, [apps]);

  const shown = res?.items || [];
  const more = useMemo(
    () => (res ? Math.max(0, res.total - shown.length) : 0), [res, shown.length]);

  return (
    <div className="apps-pane">
      <div className="apps-controls">
        {/* Grouped by category. Flat and alphabetical, 150 applications put Ableton Live next
            to Acrobat and Affinity Designer, which tells you nothing about which you want. */}
        <select className="mac-input" value={app} disabled={!apps.length}
          onChange={(e) => { setApp(e.target.value); setQ(""); }}>
          {grouped.map(([cat, list]) => (
            <optgroup key={cat} label={cat}>
              {list.map((a) => (
                <option key={a.name} value={a.name}>{a.name} ({a.actions})</option>
              ))}
            </optgroup>
          ))}
        </select>
        <input className="mac-input apps-search" type="search" value={q} placeholder="Search actions…"
          onChange={(e) => setQ(e.target.value)} />
        <div className="apps-platform">
          {["windows", "mac"].map((p) => (
            <Button key={p} size="sm" variant={platform === p ? "primary" : "secondary"}
              title="The same action is a different chord per platform, so this changes what gets bound"
              onClick={() => setPlatform(p)}>
              {p === "windows" ? "Win" : "Mac"}
            </Button>
          ))}
        </div>
      </div>

      {disabled && <div className="palette-disabled">{disabledHint}</div>}
      {err && <div className="palette-disabled">{err}</div>}

      <div className="apps-list">
        {shown.map((s, i) => (
          <button key={s.name + i} className="apps-row" disabled={disabled}
            title={`${s.name}${s.context ? ` — ${s.context}` : ""}  (${s.chord})`}
            onClick={() => onPick({
              actionCode: s.chord,
              // Matches resolveVirtualKey's convention: a chord is a shortcut_alias, a lone key
              // is a key. The encoder picks its branch from the code either way, but the stored
              // action_type is what the UI reads back.
              actionType: s.chord.includes(" + ") ? "shortcut_alias" : "key",
            })}>
            <span className="apps-row-name">{s.name}</span>
            {s.context && <span className="apps-row-ctx">{s.context}</span>}
            <span className="apps-row-chord">{formatCombo(s.chord)}</span>
          </button>
        ))}
        {!busy && !shown.length && (
          <div className="palette-disabled">
            {q ? `Nothing in ${app} matches “${q}”.` : "No shortcuts for this app on this platform."}
          </div>
        )}
        {more > 0 && (
          <div className="apps-more">
            {more} more — narrow the search to see them.
          </div>
        )}
      </div>
    </div>
  );
}
