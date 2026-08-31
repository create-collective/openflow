import { useState } from "react";

// The keybind selector (bottom-right). Tabs: Basic (keycode categories), Layers
// (bind a layer-switch to a target layer), Lighting (placeholder). Picking an
// action calls onPick with what set-key-binding needs.
const TABS = [
  { id: "basic", label: "B", title: "Basic keys" },
  { id: "layers", label: "✦", title: "Layers" },
  { id: "lighting", label: "◐", title: "Lighting" },
];

export default function ActionPalette({ catalog, layers, disabled, onPick }) {
  const [tab, setTab] = useState("basic");
  if (!catalog) return null;

  return (
    <div className="palette">
      <div className="palette-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            title={t.title}
            className={"palette-tab" + (tab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="palette-body">
        {disabled && <div className="palette-disabled">Select a key on the map first.</div>}

        {tab === "basic" &&
          catalog.categories.map((cat) => (
            <div key={cat.name} className="palette-cat">
              <div className="palette-cat-title">{cat.name}</div>
              <div className="palette-grid">
                {cat.actions.map((a) => (
                  <button
                    key={a.code}
                    className="palette-key"
                    disabled={disabled}
                    title={a.label}
                    onClick={() => onPick({ actionCode: a.code, actionType: a.actionType })}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            </div>
          ))}

        {tab === "layers" && (
          <div className="palette-cat">
            {catalog.layerActionTypes.map((lt) => (
              <div key={lt.frontendType} style={{ marginBottom: 14 }}>
                <div className="palette-cat-title">{lt.label}</div>
                <div className="palette-grid">
                  {layers.map((l, i) => (
                    <button
                      key={l.id}
                      className="palette-key layer"
                      disabled={disabled}
                      title={`${lt.label}: ${l.name}`}
                      onClick={() =>
                        onPick({
                          actionCode: lt.prefix + l.id,
                          actionType: lt.frontendType,
                        })
                      }
                    >
                      ✦ {i}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "lighting" && (
          <div className="phase-note">
            Per-key LED color lives on the Color page. Lighting-action keys
            (effects, brightness) will move here in a later pass.
          </div>
        )}
      </div>
    </div>
  );
}
