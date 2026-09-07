import { useMemo, useState } from "react";
import { formatCombo } from "../lib/combo";
import CursorIcon from "./CursorIcon";
import LayersIcon from "./LayersIcon";
import AppShortcutPicker from "./AppShortcutPicker";
import VirtualKeyboard from "./VirtualKeyboard";
import VirtualMouse from "./VirtualMouse";

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
export default function ActionPalette({
  catalog,
  layers = [],
  macros = [],
  disabled,
  onPick,
  context = "key",
  tabIds,                 // explicit ordered allowlist; overrides `context` when given
  defaultTab = "keyboard",
  filter,                 // (action, tabId) => boolean, for per-action-type constraints
  disabledHint = "Select a key on the map first.",
  className = "",
}) {
  const [tabId, setTabId] = useState(defaultTab);

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
    // is what a person scans first: the two pickers you point at, then the vocabularies, then
    // the long tail. Anything not named falls to the end rather than disappearing.
    const ORDER = ["keyboard", "mouse", "module", "basic", "apps", "shortcuts", "extended",
                   "layers", "macros"];
    const rank = (id) => (ORDER.indexOf(id) === -1 ? ORDER.length : ORDER.indexOf(id));
    return all.slice().sort((a, b) => rank(a.id) - rank(b.id));
  }, [catalog, context, tabIds, filter]);

  if (!catalog || !tabs.length) return null;
  const tab = tabs.find((t) => t.id === tabId) || tabs[0];

  return (
    <div className={"palette" + (className ? " " + className : "")}>
      <div className="palette-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            title={t.title}
            className={"palette-tab" + (tab?.id === t.id ? " active" : "")}
            onClick={() => setTabId(t.id)}
          >
            {t.id === "layers" ? <LayersIcon size={16} />
              : t.id === "mouse" ? <CursorIcon size={15} />
              : t.label}
          </button>
        ))}
      </div>

      <div className="palette-body">
        {disabled && !["keyboard", "apps", "mouse"].includes(tab?.id) && (
          <div className="palette-disabled">{disabledHint}</div>
        )}

        {tab?.id === "mouse" ? (
          // Motion pairs are axis bindings; a key position has no axis, so they are offered on
          // modules only. Buttons work in both contexts -- measured 2026-09-07, see the mouse
          // tab's note in device/actions_catalog.py.
          <VirtualMouse disabled={disabled} onPick={onPick} disabledHint={disabledHint}
                        motion={context !== "key"} />
        ) : tab?.id === "apps" ? (
          <AppShortcutPicker disabled={disabled} onPick={onPick} disabledHint={disabledHint} />
        ) : tab?.id === "keyboard" ? (
          <VirtualKeyboard disabled={disabled} onPick={onPick} disabledHint={disabledHint} />
        ) : tab?.id === "macros" ? (
          <div className="palette-cat">
            <div className="palette-cat-title">Macros <span className="palette-count">{macros.length}</span></div>
            {macros.length === 0 ? (
              <div className="palette-disabled">No macros yet. Create them on the Macros page.</div>
            ) : (
              <div className="palette-grid wide">
                {macros.map((m) => (
                  <button
                    key={m.id}
                    className="palette-key"
                    disabled={disabled}
                    title={`Bind macro: ${m.name}`}
                    onClick={() => onPick({ actionCode: m.id, actionType: "macro" })}
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
                <div className="palette-grid">
                  {layers.map((l, i) => (
                    <button
                      key={l.id}
                      className="palette-key layer"
                      disabled={disabled}
                      title={`${lt.label}: ${l.name}`}
                      onClick={() =>
                        onPick({ actionCode: lt.prefix + l.id, actionType: lt.frontendType })
                      }
                    >
                      <LayersIcon size={13} /> {i}
                    </button>
                  ))}
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
                      className={"palette-key" + (a.comingSoon ? " soon" : "")}
                      disabled={disabled || a.comingSoon}
                      title={tab.id === "shortcuts" ? `${a.name || a.label}  (${a.code})` : (a.comingSoon ? `${a.label} (coming soon)` : `${a.name || a.label} (${a.code})`)}
                      onClick={() => onPick({ actionCode: a.code, actionType: a.actionType })}
                    >
                      {tab.id === "shortcuts" ? formatCombo(a.code) : a.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
      </div>
    </div>
  );
}
