import { useEffect, useRef, useState } from "react";

// Layer selector (top-left): profile name + ordered layers with a per-layer
// 3-dot submenu (rename / use as base / duplicate / delete) and an add-layer row.
export default function LayerList({
  profile,
  layers,
  activeLayerId,
  onSelect,
  onAdd,
  onRename,
  onDuplicate,
  onDelete,
  onSetBase,
}) {
  const [menuFor, setMenuFor] = useState(null); // layer id whose menu is open
  const [renaming, setRenaming] = useState(null); // layer id being renamed
  const [renameVal, setRenameVal] = useState("");
  const [confirmDel, setConfirmDel] = useState(null);
  const [adding, setAdding] = useState(false);
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
      <div className="layer-profile">
        <span className="layer-profile-dot" />
        {profile?.name || "Profile"}
      </div>

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
        <button className="layer-add" onClick={() => setAdding(true)}>+ Add layer</button>
      )}
    </div>
  );
}
