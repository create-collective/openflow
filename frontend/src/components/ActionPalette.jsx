import { useState } from "react";

// The keybind selector (bottom-right). Tabs come from the backend catalog:
// B (basic), + (extended), ✦ (layers), ↗ (shortcuts). Picking an action calls
// onPick with what set-key-binding needs.
export default function ActionPalette({ catalog, layers, disabled, onPick }) {
  const [tabId, setTabId] = useState("basic");
  if (!catalog) return null;
  const tabs = catalog.tabs || [];
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
            {t.label}
          </button>
        ))}
      </div>

      <div className="palette-body">
        {disabled && <div className="palette-disabled">Select a key on the map first.</div>}

        {tab?.id === "layers"
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
                      ✦ {i}
                    </button>
                  ))}
                </div>
              </div>
            ))
          : tab?.categories.map((cat) => (
              <div key={cat.name} className="palette-cat">
                <div className="palette-cat-title">{cat.name}</div>
                <div className="palette-grid">
                  {cat.actions.map((a) => (
                    <button
                      key={a.code}
                      className={"palette-key" + (a.comingSoon ? " soon" : "")}
                      disabled={disabled || a.comingSoon}
                      title={a.comingSoon ? `${a.label} (coming soon)` : a.label}
                      onClick={() => onPick({ actionCode: a.code, actionType: a.actionType })}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
      </div>
    </div>
  );
}
