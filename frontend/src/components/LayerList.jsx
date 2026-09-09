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
  onCountReferences,
  onReorder,
  notice,
  onDismissNotice,
  profiles = [],
}) {
  const [menuFor, setMenuFor] = useState(null); // layer id whose menu is open
  const [renaming, setRenaming] = useState(null); // layer id being renamed
  const [renameVal, setRenameVal] = useState("");
  const [confirmDel, setConfirmDel] = useState(null);
  // How many keys switch TO the layer being deleted. Those bindings cannot be
  // repointed automatically, so the user is told before they are cleared.
  const [delRefs, setDelRefs] = useState(null);
  const [adding, setAdding] = useState(false);
  // Import has two lanes: a file, or a layer that already exists in this app.
  const [importOpen, setImportOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const rootRef = useRef(null);
  // Which row the gesture picked up, held in a REF so that starting a drag re-renders nothing.
  // That mattered enormously with native HTML5 drag -- any re-render during dragstart restyles
  // the source and CANCELS the drag -- and it is still the right shape here: a pointer gesture
  // should not repaint the list on every move.
  const dragIdRef = useRef(null);
  const rowRefs = useRef({});

  /** Which layer row is under this viewport Y? Measured live, so it stays correct if the list
      scrolls mid-gesture. */
  function rowAt(clientY) {
    for (const [id, el] of Object.entries(rowRefs.current)) {
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (clientY >= r.top && clientY <= r.bottom) return id;
    }
    return null;
  }
  const [dragOver, setDragOver] = useState(null);

  // A pointer gesture cannot be left hanging by the browser the way a drag session could, but a
  // pointerup that lands outside the window still needs to clear our state.
  useEffect(() => {
    function clear() { dragIdRef.current = null; setDragOver(null); }
    window.addEventListener("pointerup", clear);
    window.addEventListener("pointercancel", clear);
    return () => {
      window.removeEventListener("pointerup", clear);
      window.removeEventListener("pointercancel", clear);
    };
  }, []);

  useEffect(() => {
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setMenuFor(null);
        setConfirmDel(null);
        setDelRefs(null);
        setImportOpen(false);
      }
    }
    function onKey(e) {
      if (e.key === "Escape") {
        setMenuFor(null);
        setConfirmDel(null);
        setDelRefs(null);
        setImportOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
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
      {notice && (
        <div className="layer-note">
          <span>{notice}</span>
          <button className="layer-note-x" title="Dismiss" onClick={onDismissNotice}>✕</button>
        </div>
      )}
      {layers.map((l, i) => (
        <div key={l.id}
             ref={(el) => { if (el) rowRefs.current[l.id] = el; else delete rowRefs.current[l.id]; }}
             className={"layer-row" + (l.id === activeLayerId ? " active" : "")
               + (dragOver === l.id ? " dragover" : "")}>
          {/* POINTER EVENTS, NOT HTML5 DRAG.
              Native drag failed four different ways here: a <button> covering the row blocks
              drag initiation; any re-render during dragstart restyles the source and CANCELS
              the drag; a leftover duplicate handler on the row defeated the fix for that; and
              once a drag is cancelled mid-initiation Chrome holds a session that never ends,
              which reads to the user as the whole page freezing.
              Pointer events have none of that: nothing is snapshotted, there is no session to
              wedge, and the browser cannot cancel anything behind our back. Pointer capture
              means we keep receiving moves even outside the element. */}
          <span
            className="layer-grip"
            title="Drag to reorder"
            aria-label="Drag to reorder"
            onPointerDown={(e) => {
              if (renaming) return;
              e.preventDefault();
              e.currentTarget.setPointerCapture(e.pointerId);
              dragIdRef.current = l.id;
            }}
            onPointerMove={(e) => {
              if (!dragIdRef.current) return;
              const over = rowAt(e.clientY);
              setDragOver(over && over !== dragIdRef.current ? over : null);
            }}
            onPointerUp={(e) => {
              const dragId = dragIdRef.current;
              dragIdRef.current = null;
              try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
              const over = rowAt(e.clientY);
              setDragOver(null);
              if (!dragId || !over || over === dragId) return;
              // Rebuild the whole order and hand it over -- the backend takes a complete list
              // rather than a move, so an interrupted gesture can never half-order the layers.
              const ids = layers.map((x) => x.id).filter((x) => x !== dragId);
              ids.splice(ids.indexOf(over), 0, dragId);
              onReorder(ids);
            }}
            onPointerCancel={() => { dragIdRef.current = null; setDragOver(null); }}
          >⠿</span>

          {renaming === l.id ? (
            <input
              className="layer-rename"
              draggable={false}
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
            <button className="layer-item" draggable={false} onClick={() => onSelect(l.id)}>
              <span className="layer-index">{i}</span>
              <span className="layer-name">{l.name}</span>
            </button>
          )}

          <button
            className="layer-menu-btn"
            draggable={false}
            title="Layer options"
            onClick={() => { setMenuFor(menuFor === l.id ? null : l.id); setConfirmDel(null); }}
          >
            ⋯
          </button>

          {menuFor === l.id && (
            <div className="layer-menu" draggable={false}>
              <button onClick={() => startRename(l)}>Rename</button>
              <button onClick={() => { onSetBase(l.id); setMenuFor(null); }} disabled={i === 0}>
                Use as base layer
              </button>
              <button onClick={() => { onDuplicate(l.id); setMenuFor(null); }}>Duplicate</button>
              <button onClick={() => { onExportLayer(l.id); setMenuFor(null); }}>Export to file…</button>
              {confirmDel === l.id ? (
                <>
                  {delRefs > 0 && (
                    <div className="layer-del-warn">
                      {delRefs} key{delRefs === 1 ? "" : "s"} switch to this layer.
                      Deleting it clears {delRefs === 1 ? "that binding" : "those bindings"}.
                    </div>
                  )}
                  <button className="danger"
                          onClick={() => { onDelete(l.id); setMenuFor(null); setConfirmDel(null); setDelRefs(null); }}>
                    Really delete?
                  </button>
                </>
              ) : (
                <button
                  className="danger"
                  disabled={layers.length <= 1}
                  onClick={async () => {
                    setConfirmDel(l.id);
                    setDelRefs(null);
                    try {
                      const r = await onCountReferences(l.id);
                      setDelRefs(r?.count ?? 0);
                    } catch { setDelRefs(0); }
                  }}
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
