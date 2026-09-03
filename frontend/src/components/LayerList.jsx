import { useEffect, useRef, useState } from "react";

// Layer selector (top-left): profile name + ordered layers with a per-layer
// 3-dot submenu (rename / use as base / duplicate / delete) and an add-layer row.
export default function LayerList({
  layers,
  activeLayerId,
  onSelect,
  onAdd,
  onRename,
  onDuplicate,
  onDelete,
  onSetBase,
  onExportLayer,
  onImportLayer,
  onCopyLayerFrom,
  profiles = [],
}) {
  const [menuFor, setMenuFor] = useState(null); // layer id whose menu is open
  const [renaming, setRenaming] = useState(null); // layer id being renamed
  const [renameVal, setRenameVal] = useState("");
  const [confirmDel, setConfirmDel] = useState(null);
  const [adding, setAdding] = useState(false);
  // Import has two lanes: a file, or a layer that already exists in this app.
  const [importOpen, setImportOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const rootRef = useRef(null);

  useEffect(() => {
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setMenuFor(null);
        setConfirmDel(null);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function startRename(l) {
    setRenaming(l.id);
    setRenameVal(l.name);
    setMenuFor(null);
  }
  function commitRename(l) {
    const v = renameVal.trim();
    if (v && v !== l.name) onRename(l.id, v);
    setRenaming(null);
  }

  return (
    <div className="layer-list" ref={rootRef}>
      {layers.map((l, i) => (
        <div key={l.id} className={"layer-row" + (l.id === activeLayerId ? " active" : "")}>
          {renaming === l.id ? (
            <input
              className="layer-rename"
              autoFocus
              value={renameVal}
              onChange={(e) => setRenameVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitRename(l);
                if (e.key === "Escape") setRenaming(null);
              }}
              onBlur={() => commitRename(l)}
            />
          ) : (
            <button className="layer-item" onClick={() => onSelect(l.id)}>
              <span className="layer-index">{i}</span>
              <span className="layer-name">{l.name}</span>
            </button>
          )}

          <button
            className="layer-menu-btn"
            title="Layer options"
            onClick={() => { setMenuFor(menuFor === l.id ? null : l.id); setConfirmDel(null); }}
          >
            ⋯
          </button>

          {menuFor === l.id && (
            <div className="layer-menu">
              <button onClick={() => startRename(l)}>Rename</button>
              <button onClick={() => { onSetBase(l.id); setMenuFor(null); }} disabled={i === 0}>
                Use as base layer
              </button>
              <button onClick={() => { onDuplicate(l.id); setMenuFor(null); }}>Duplicate</button>
              <button onClick={() => { onExportLayer(l.id); setMenuFor(null); }}>Export to file…</button>
              {confirmDel === l.id ? (
                <button className="danger" onClick={() => { onDelete(l.id); setMenuFor(null); setConfirmDel(null); }}>
                  Really delete?
                </button>
              ) : (
                <button
                  className="danger"
                  disabled={layers.length <= 1}
                  onClick={() => setConfirmDel(l.id)}
                >
                  Delete
                </button>
              )}
            </div>
          )}
        </div>
      ))}

      {adding ? (
        <input
          className="layer-rename"
          autoFocus
          placeholder="Layer name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { if (newName.trim()) onAdd(newName.trim()); setAdding(false); setNewName(""); }
            if (e.key === "Escape") { setAdding(false); setNewName(""); }
          }}
          onBlur={() => { if (newName.trim()) onAdd(newName.trim()); setAdding(false); setNewName(""); }}
        />
      ) : (
        <div className="layer-add-row">
          <button className="layer-add" onClick={() => setAdding(true)}>+ Add layer</button>
          <span className="layer-import-wrap">
            <button className="layer-add import" title="Import a layer from a file, or copy one from another profile"
                    onClick={() => setImportOpen((v) => !v)}>Import…</button>
            {importOpen && (
              <div className="layer-import-menu">
                <button onClick={() => { setImportOpen(false); onImportLayer(); }}>
                  From a file…
                </button>
                <div className="profile-menu-sep" />
                <div className="layer-import-head">Copy from a profile</div>
                {profiles.flatMap((p) =>
                  (p.layers || []).map((l) => (
                    <button key={`${p.id}:${l.id}`}
                            onClick={() => { setImportOpen(false); onCopyLayerFrom(l.id); }}
                            title={`Copy "${l.name}" from ${p.name}`}>
                      <span className="layer-import-layer">{l.name}</span>
                      <span className="layer-import-profile">{p.name}</span>
                    </button>
                  ))
                )}
                {profiles.length === 0 && <div className="palette-disabled">No other profiles.</div>}
              </div>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
