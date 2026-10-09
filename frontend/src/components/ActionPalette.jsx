import { useMemo, useState } from "react";
import { formatCombo } from "../lib/combo";
import CursorIcon from "./CursorIcon";
import LayersIcon from "./LayersIcon";
import AppShortcutPicker from "./AppShortcutPicker";
import VirtualKeyboard from "./VirtualKeyboard";
import VirtualMouse from "./VirtualMouse";
import { ActionIcon, iconNameFor } from "../lib/icons";
import Badge from "./ui/Badge";
import Notice from "./ui/Notice";
import Tabs from "./ui/Tabs";

// The action selector, shared by the keymap editor and by module gestures.
//
// Tabs come from the backend catalog -- B (basic), + (extended), ✦ (layers), ↗ (shortcuts) --
// plus a virtual keyboard and macros synthesized here. Picking calls onPick with exactly what a
// binding write needs, and that contract is deliberately frozen: both call sites depend on it.
//
// WHICH tabs appear is decided by the tab, not by the caller. Each catalog tab declares the
// contexts it belongs in, and this filters on `context`. That is an allowlist on purpose -- with
// a hide-list, every tab added later would show up in the keymap editor until somebody
// remembered to exclude it.
/**
 * Why a Toggle Layer target can be refused. Returns a reason string, or null if it is fine.
 *
 * TOGGLING THE BASE LAYER DOES NOTHING USEFUL, and NayaFlow does not allow it either: its
 * renderer drops the first entry from the target list for this action type specifically
 * (`actionType === "layer_polite_toggle" && (l = l.toSpliced(0, 1))`). `&tog 0` toggles the base
 * layer, which does not deactivate the layer you are standing on -- so it works outward to
 * layers 1 and 2 and never back, which is exactly how a keyboard ends up stuck.
 *
 * Targeting a LOWER layer has the same problem for a different reason: the layer you are on sits
 * above it and hides it. NayaFlow permits that one; we warn rather than block, because unlike the
 * base-layer case we have reasoned it out rather than measured it.
 *
 * Targeting the layer you are ON is the exception and stays allowed -- `&tog N` from layer N
 * turns that layer off, which is the ordinary "press the same key to come back" idiom.
 */
export function toggleBlock(actionType, targetIndex, currentIndex) {
  if (actionType !== "layer_polite_toggle") return null;
  if (targetIndex === 0) {
    return "Toggle can't target the base layer — it won't bring you back. Use Force Layer.";
  }
  if (currentIndex != null && targetIndex < currentIndex) {
    return `Toggle can't reach layer ${targetIndex} from layer ${currentIndex} — this layer sits `
      + `above it. Use Force Layer, or toggle layer ${currentIndex} off.`;
  }
  return null;
}

// The word beside each tab's glyph. The glyph alone (B, +, ✦, ↗) was the whole label until the
// storyboard's icon + label pills (2026-09-17).
const TAB_WORD = {
  keyboard: "Keyboard", mouse: "Mouse", basic: "Basic", apps: "Apps", shortcuts: "Shortcuts",
  extended: "Extended", layers: "Layers", macros: "Macros", module: "Module",
};

export default function ActionPalette({
  assigning = null,       // "A → Hold": what a pick writes to, shown in the head
  catalog,
  layers = [],
  currentLayerIndex = null,   // which layer the key being edited lives on; gates layer toggles
  macros = [],
  disabled,
  onPick,
  context = "key",
  tabIds,                 // explicit ordered allowlist; overrides `context` when given
  defaultTab = "keyboard",
  filter,                 // (action, tabId) => boolean, for per-action-type constraints
  disabledHint = "Select a key on the map first.",
  className = "",
  mouseDirections = false,  // a split-axis half is selected: single directions, not pairs
}) {
  const [tabId, setTabId] = useState(defaultTab);
  const [query, setQuery] = useState("");

  // Tab list and per-tab filtering, recomputed only when the inputs actually change.
  const tabs = useMemo(() => {
    if (!catalog) return [];
    const inContext = (t) =>
      tabIds ? tabIds.includes(t.id) : (t.contexts || ["key", "module"]).includes(context);

    const fromCatalog = (catalog.tabs || [])
      .filter(inContext)
      .map((t) => {
        if (!filter) return t;
        // Drop actions the caller rejects, then categories that empty out -- an empty category
        // renders a bare heading with a count of 0.
        const categories = (t.categories || [])
          .map((c) => ({ ...c, actions: (c.actions || []).filter((a) => filter(a, t.id)) }))
          .filter((c) => c.actions.length);
        return { ...t, categories };
      })
      // ...and tabs whose categories all emptied out. `layers` is exempt: its categories are
      // synthesized here from the caller's layer list, so an empty array is normal.
      // `layers` and `apps` both ship with empty categories on purpose -- one is synthesized
      // from the caller's layer list, the other has its own render branch -- so an empty array
      // is normal for them and must not be read as "filtered to nothing".
      .filter((t) => ["layers", "apps", "mouse"].includes(t.id) || !filter
                     || (t.categories || []).length);

    const all = [
      ...(inContext({ id: "keyboard", contexts: ["key", "module"] })
        ? [{ id: "keyboard", label: "⌨", title: "Virtual keyboard" }] : []),
      ...fromCatalog,
      // Macros are a keymap concept; there is no evidence a module gesture can hold one.
      ...(inContext({ id: "macros", contexts: ["key"] })
        ? [{ id: "macros", label: "⚡", title: "Macros" }] : []),
    ];
    // Ordered here rather than left to whatever the catalog happens to list, because the strip
    // is what a person scans first: the two pickers you point at, then the key vocabularies
    // (basic, extended, layers), then the app side (apps, shortcuts, macros); the owner set
    // this order on 2026-09-17. Module only appears on the Modules page and keeps its place
    // after Mouse. Anything not named falls to the end rather than disappearing.
    const ORDER = ["keyboard", "mouse", "module", "basic", "extended", "layers", "apps",
                   "shortcuts", "macros"];
    const rank = (id) => (ORDER.indexOf(id) === -1 ? ORDER.length : ORDER.indexOf(id));
    return all.slice().sort((a, b) => rank(a.id) - rank(b.id));
  }, [catalog, context, tabIds, filter]);

  // One search over every tab at once: code, keycap legend, NayaFlow's name, our alias and
  // the tooltip, plus the 5,000-odd application shortcuts by name and chord. The names are
  // the key -- "wireless" finds BT_OUT, "brightness" finds the LED keys, "paste" finds every
  // app's paste chord -- which is why this waited on the names work.
  //
  // RANKED, because it was not. Hits used to be pushed in iteration order and never sorted, so
  // "windows" answered with nine macOS entries before the first Windows one -- not because they
  // matched better but because the module and shortcuts TABS are walked before the app-shortcut
  // corpus. Three things fix it: score by where and how well the query landed, drop duplicates,
  // and cap AFTER sorting rather than during the walk (the old cap returned early from inside
  // the tab loop, so a broad query could never reach the shortcuts at all).
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!catalog || q.length < 2) return null;

    // Where a hit landed, best first. A whole-word match beats a match inside a longer word:
    // "windows" should prefer "Cycle windows" over "Windows Terminal profile 2".
    // Built by hand rather than with a constructed RegExp: the query is user text, so it
    // would have to be escaped, and an escaping slip there is both a crash and a ReDoS.
    const alnum = (ch) => !!ch && /[a-z0-9]/.test(ch);
    const isWordHit = (v) => {
      for (let i = v.indexOf(q); i !== -1; i = v.indexOf(q, i + 1)) {
        if (!alnum(v[i - 1]) && !alnum(v[i + q.length])) return true;
      }
      return false;
    };
    const score = (f, weight) => {
      if (!f) return 0;
      const v = String(f).toLowerCase();
      if (v === q) return weight + 3;
      if (isWordHit(v)) return weight + 2;
      if (v.startsWith(q)) return weight + 1;
      return v.includes(q) ? weight : 0;
    };
    // Field weights. The code is what actually gets flashed, so an exact code match wins outright.
    // `group` matters more than it looks: the Windows entries live in a group literally called
    // "Windows & desktops", which is the strongest signal of intent we hold and was previously
    // used only to match, never to rank. Tooltips rank last -- 178 of 377 are truncated by the
    // scrape, so a hit in one is the least trustworthy kind.
    // The best field decides the rank; the others break ties. Without that second term,
    // "Cycle windows" (in the group "Windows & desktops") and "Minimize All Windows of App"
    // (in "MacOS") both scored a whole-word hit on the name and tied at 42, and the tie fell to
    // walk order -- which is how macOS kept leading a search for "windows". Corroboration across
    // fields is exactly what separates them, so it is summed and used underneath the primary.
    const rate = (o) => {
      const all = [score(o.code, 50), score(o.label, 40), score(o.name, 40),
                   score(o.alias, 30), score(o.group, 20), score(o.tooltip, 10)];
      const best = Math.max(...all);
      return best === 0 ? 0 : best * 1000 + all.reduce((a, b) => a + b, 0);
    };

    const out = [];
    const seen = new Set();          // by what would be bound, so the same chord cannot list twice
    const push = (key, r) => { if (!seen.has(key)) { seen.add(key); out.push(r); } };

    for (const t of tabs) {
      for (const c of t.categories || []) {
        for (const a of c.actions || []) {
          const s = rate({ code: a.code, label: a.label, name: a.name, alias: a.alias,
                           group: c.name, tooltip: a.tooltip });
          if (s) push(`${a.actionType}/${a.code}`,
                      { key: `${t.id}/${a.code}`, tab: t, cat: c.name, action: a, score: s,
                        pick: { actionCode: a.code, actionType: a.actionType } });
        }
      }
    }
    for (const [code, sc] of Object.entries(catalog.shortcuts || {})) {
      const s = rate({ code, name: sc.name, label: sc.name, group: sc.group, tooltip: sc.chord });
      if (!s) continue;
      const bind = sc.chord || code;
      push(`shortcut/${bind}`,
           { key: `apps/${code}`, tab: { id: "apps", title: "Application shortcuts" },
             cat: sc.group || "Shortcut",
             action: { code, label: sc.name, name: sc.name, tooltip: sc.chord }, score: s,
             pick: { actionCode: bind,
                     actionType: bind.includes(" + ") ? "shortcut_alias" : "key" } });
    }
    // Stable within a score: the walk order above is itself meaningful (the tab strip is ordered
    // by how often it is reached for), so equal-scoring hits keep it rather than being shuffled.
    return out.sort((a, b) => b.score - a.score).slice(0, 80);
  }, [catalog, tabs, query]);

  if (!catalog || !tabs.length) return null;
  const tab = tabs.find((t) => t.id === tabId) || tabs[0];
  // What a hover says about an action: NayaFlow's name, its tooltip, then the code. Every
  // line is something a person can act on; the code alone ("BT_OUT") told them nothing.
  const describe = (a) => [a.name || a.label, a.tooltip, a.alias && a.alias !== a.name ? `also: ${a.alias}` : null, `(${a.code})`]
    .filter(Boolean).join("\n");

  return (
    <div className={"palette" + (className ? " " + className : "")}>
      {/* One head row: the title, what a pick writes to, the categories as icon + label pills,
          and the search right after them. The body under it is the tab, or the results. */}
      <div className="palette-head">
        <span className="palette-title">Actions</span>
        {assigning && <span className="palette-assign">Assigning: <b>{assigning}</b></span>}
        <Tabs
          variant="pills"
          ariaLabel="Action categories"
          value={tab?.id}
          onChange={setTabId}
          items={tabs.map((t) => ({
            id: t.id,
            title: t.title,
            icon: t.id === "layers" ? <LayersIcon size={16} />
              : t.id === "mouse" ? <CursorIcon size={15} />
              : <span className="ui-tab-icon" aria-hidden="true">{t.label}</span>,
            label: TAB_WORD[t.id] || t.title,
          }))}
        />
        <input
          className="palette-search"
          type="search"
          value={query}
          placeholder="Search every action — wireless, brightness, paste…"
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search all actions"
        />
      </div>

      <div className="palette-body">
        {disabled && !["keyboard", "apps", "mouse"].includes(tab?.id) && (
          <div className="palette-disabled">{disabledHint}</div>
        )}

        {results ? (
          <div className="palette-cat">
            <div className="palette-cat-title">
              Results <span className="palette-count">{results.length}{results.length >= 80 ? "+" : ""}</span>
            </div>
            {results.length === 0 && <div className="palette-disabled">Nothing matches “{query}”.</div>}
            <div className="palette-results">
              {results.map((r) => (
                <button
                  key={r.key}
                  className={"palette-result" + (disabled ? " disabled" : "")}
                  aria-disabled={disabled || undefined}
                  title={describe(r.action)}
                  onClick={() => !disabled && onPick(r.pick)}
                >
                  <span className="palette-result-name">
                    <ActionIcon name={iconNameFor(r.action.code, catalog.names)} size={16} className="inline" />
                    {r.action.name || r.action.label}
                  </span>
                  <span className="palette-result-where">{r.tab.title || r.tab.id} · {r.cat}</span>
                  {r.action.tooltip && <span className="palette-result-tip">{r.action.tooltip}</span>}
                </button>
              ))}
            </div>
          </div>
        ) : tab?.id === "mouse" ? (
          // Motion pairs are axis bindings; a key position has no axis, so they are offered on
          // modules only. Buttons work in both contexts -- measured 2026-09-07, see the mouse
          // tab's note in device/actions_catalog.py.
          <VirtualMouse disabled={disabled} onPick={onPick} disabledHint={disabledHint}
                        motion={context !== "key"} directions={context !== "key" && mouseDirections} />
        ) : tab?.id === "apps" ? (
          <AppShortcutPicker disabled={disabled} onPick={onPick} disabledHint={disabledHint} />
        ) : tab?.id === "keyboard" ? (
          <VirtualKeyboard disabled={disabled} onPick={onPick} disabledHint={disabledHint} />
        ) : tab?.id === "macros" ? (
          // Shown, but NOT bindable. The keyboard's macro table is not implemented in firmware:
          // it answers READ_MACRO_LIST/READ_MACRO_DATA and holds nothing, and every
          // WRITE_MACRO_LIST/WRITE_MACRO_DATA we have sent -- seven encoding variants -- was
          // ACKed and discarded. NayaCore never sends those opcodes either, even when flashing
          // a profile that contains a macro. See docs/module-field-map.md (C9/C10).
          //
          // Binding one used to be possible: it saved, the keycap read "Macro", and flash.py
          // dropped it silently at write time. Showing them greyed with the reason is honest;
          // hiding the tab would just make the same dead end harder to understand.
          <div className="palette-cat">
            <div className="palette-cat-title">
              Macros <span className="palette-count">{macros.length}</span>
              <Badge size="xs" tone="warn" style={{ marginLeft: 8 }}>
                experimental
              </Badge>
            </div>
            <Notice size="sm" tone="warn" className="palette-note">
              Macros cannot be bound to a key yet. The keyboard reserves the macro behavior type
              but implements no macro table, so a bound macro would never reach the board. You can
              still build and edit them on the Macros page.
            </Notice>
            {macros.length === 0 ? (
              <div className="palette-disabled">No macros yet. Create them on the Macros page.</div>
            ) : (
              <div className="palette-grid wide">
                {macros.map((m) => (
                  <button
                    key={m.id}
                    className="palette-key soon"
                    disabled
                    title="Not bindable: the keyboard has no macro table (firmware limitation)."
                  >
                    ⚡ {m.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : tab?.id === "layers"
          ? (catalog.layerActionTypes || []).map((lt) => (
              <div key={lt.frontendType} className="palette-cat">
                <div className="palette-cat-title">{lt.label}</div>
                {lt.frontendType === "layer_polite_toggle" && (
                  <Notice size="sm" tone="warn" className="palette-note">
                    Toggle turns a layer on and off. It can’t bring you <em>back down</em>: a lower
                    layer is hidden by the one you’re on, and toggling the base layer does nothing
                    at all. Use <strong>Force Layer</strong> to return.
                  </Notice>
                )}
                <div className="palette-grid">
                  {layers.map((l, i) => {
                    const block = toggleBlock(lt.frontendType, i, currentLayerIndex);
                    return (
                      <button
                        key={l.id}
                        className={"palette-key layer" + (block ? " soon" : "") + (disabled ? " disabled" : "")}
                        aria-disabled={disabled || !!block || undefined}
                        title={block ? block : `${lt.label}: ${l.name}`}
                        onClick={() => !disabled && !block
                          && onPick({ actionCode: lt.prefix + l.id, actionType: lt.frontendType })}
                      >
                        <LayersIcon size={13} /> {i}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          // `tab.categories` is guarded, not just `tab`: the synthetic keyboard tab has no
          // categories at all, and under filtering `tabs[0]` can become it.
          : (tab?.categories || []).map((cat) => (
              <div key={cat.name} className="palette-cat">
                <div className="palette-cat-title">{cat.name} <span className="palette-count">{cat.actions.length}</span></div>
                {/* Module action labels are sentences with the chord in them ("Cycle windows
                    backwards (Alt + Shift + Tab)"), so the 44px key grid truncates them to
                    nonsense. `wide` is the same treatment macros already get. */}
                <div className={"palette-grid" + (tab.id === "shortcuts" ? " combo"
                  : tab.id === "module" ? " wide" : "")}>
                  {cat.actions.map((a, i) => (
                    <button
                      key={a.code + "-" + i}
                      // Disabled by CLASS, not attribute: a disabled control gets no hover, so
                      // its title never showed -- and the palette is disabled whenever no key
                      // is selected, which is exactly when people read it to decide.
                      className={"palette-key" + (disabled ? " disabled" : "")}
                      aria-disabled={disabled || undefined}
                      title={describe(a)}
                      onClick={() => !disabled
                        && onPick({ actionCode: a.code, actionType: a.actionType })}
                    >
                      {(() => {
                        // NayaFlow's keycap look: the icon alone where one exists, the name on
                        // hover. Letters and digits keep their text (lib/icons.jsx). The wide
                        // module grid shows sentences, so there the icon sits before the text.
                        const icon = iconNameFor(a.code, catalog.names);
                        if (tab.id === "shortcuts") {
                          // A shortcut is its chord; the icon says what the chord does.
                          return icon
                            ? <><ActionIcon name={icon} size={22} /><span className="palette-combo">{formatCombo(a.code)}</span></>
                            : formatCombo(a.code);
                        }
                        // The module grid is sentences ("Cycle windows backwards (Alt + Shift +
                        // Esc)"), so its cell is a legible icon beside left-aligned text rather
                        // than a keycap; a 16px glyph stacked over centred text read as nothing.
                        if (tab.id === "module") {
                          return <>{icon && <ActionIcon name={icon} size={32} />}<span className="palette-key-text">{a.label}</span></>;
                        }
                        if (!icon) return a.label;
                        return <ActionIcon name={icon} size={34} />;
                      })()}
                    </button>
                  ))}
                </div>
              </div>
            ))}
      </div>
    </div>
  );
}
