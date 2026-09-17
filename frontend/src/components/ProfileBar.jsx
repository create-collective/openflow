import { useEffect, useRef, useState } from "react";
import IconButton from "./ui/IconButton";

// Profile selector: switch profiles, plus a 3-dot menu (Rename / Duplicate /
// Export / Load from file / Delete). Sits above the layer list.
export default function ProfileBar({
  profiles,
  activeProfileId,
  onSwitch,
  onNew,
  onRename,
  onDuplicate,
  onDelete,
  onExport,
  onImport,
}) {
  const [switchOpen, setSwitchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameVal, setRenameVal] = useState("");
  const [confirmDel, setConfirmDel] = useState(false);
  const rootRef = useRef(null);

  const active = profiles.find((p) => p.id === activeProfileId) || profiles[0];

  useEffect(() => {
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setSwitchOpen(false);
        setMenuOpen(false);
        setConfirmDel(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function commitRename() {
    const v = renameVal.trim();
    if (v && active && v !== active.name) onRename(active.id, v);
    setRenaming(false);
  }

  return (
    <div className="profile-bar" ref={rootRef}>
      {renaming ? (
        <input
          className="layer-rename"
          autoFocus
          value={renameVal}
          onChange={(e) => setRenameVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") setRenaming(false);
          }}
          onBlur={commitRename}
        />
      ) : (
        <button className="profile-name" onClick={() => { setSwitchOpen((v) => !v); setMenuOpen(false); }}>
          <span className="layer-profile-dot" />
          <span className="profile-name-text">{active?.name || "Profile"}</span>
          <span className="profile-caret">▾</span>
        </button>
      )}

      <IconButton
        className="profile-menu-btn"
        title="Profile options"
        onClick={() => { setMenuOpen((v) => !v); setSwitchOpen(false); setConfirmDel(false); }}
      >
        ⋯
      </IconButton>

      {switchOpen && (
        <div className="profile-menu switch">
          {profiles.map((p) => (
            <button
              key={p.id}
              className={p.id === activeProfileId ? "active" : ""}
              onClick={() => { onSwitch(p.id); setSwitchOpen(false); }}
            >
              {p.id === activeProfileId ? "● " : "○ "}{p.name}
            </button>
          ))}
          <div className="profile-menu-sep" />
          <button onClick={() => { onNew(); setSwitchOpen(false); }}>+ New profile</button>
          <button onClick={() => { onExport(active.id); setSwitchOpen(false); }}>Export this profile…</button>
          <button onClick={() => { onImport(); setSwitchOpen(false); }}>Load profile from file…</button>
        </div>
      )}

      {menuOpen && (
        <div className="profile-menu">
          <button onClick={() => { setRenameVal(active?.name || ""); setRenaming(true); setMenuOpen(false); }}>Rename</button>
          <button onClick={() => { onDuplicate(active.id); setMenuOpen(false); }}>Duplicate</button>
          <button onClick={() => { onExport(active.id); setMenuOpen(false); }}>Export to file…</button>
          <button onClick={() => { onImport(); setMenuOpen(false); }}>Load profile from file…</button>
          {confirmDel ? (
            <button className="danger" onClick={() => { onDelete(active.id); setMenuOpen(false); setConfirmDel(false); }}>
              Really delete?
            </button>
          ) : (
            <button className="danger" disabled={profiles.length <= 1} onClick={() => setConfirmDel(true)}>
              Delete
            </button>
          )}
        </div>
      )}
    </div>
  );
}
