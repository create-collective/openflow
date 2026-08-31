import { useState } from "react";
import { formatCombo } from "../lib/combo";
import LayersIcon from "./LayersIcon";

// The keybind selector (bottom-right). Tabs come from the backend catalog:
// B (basic), + (extended), ✦ (layers), ↗ (shortcuts). Picking an action calls
// onPick with what set-key-binding needs.
export default function ActionPalette({ catalog, layers, macros = [], disabled, onPick }) {
  const [tabId, setTabId] = useState("basic");
  if (!catalog) return null;
  const tabs = [...(catalog.tabs || []), { id: "macros", label: "⚡", title: "Macros" }];
  const tab = tabs.find((t) => t.id === tabId) || tabs[0];

  return (
    <div className="palette">
      <div className="palette-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            title={t.title}
            className={"palette-tab" + (tab?.id === t.id ? " active" : "")}
            onClick={() => setTabId(t.id)}
          >
            {t.id === "layers" ? <LayersIcon size={16} /> : t.label}
          </button>
        ))}
      </div>

      <div className="palette-body">
        {disabled && <div className="palette-disabled">Select a key on the map first.</div>}

        {tab?.id === "macros" ? (
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
          ? catalog.layerActionTypes.map((lt) => (
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
          : tab?.categories.map((cat) => (
              <div key={cat.name} className="palette-cat">
                <div className="palette-cat-title">{cat.name} <span className="palette-count">{cat.actions.length}</span></div>
                <div className={"palette-grid" + (tab.id === "shortcuts" ? " combo" : "")}>
                  {cat.actions.map((a, i) => (
                    <button
                      key={a.code + "-" + i}
                      className={"palette-key" + (a.comingSoon ? " soon" : "")}
                      disabled={disabled || a.comingSoon}
                      title={tab.id === "shortcuts" ? `${a.label}  (${a.code})` : (a.comingSoon ? `${a.label} (coming soon)` : `${a.label} (${a.code})`)}
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
