import { useEffect, useRef, useState } from "react";

// Choosing which profile a module runs, from the board's module row.
//
// One profile per module, so these are radios rather than checkboxes -- a bay holds exactly one
// slot number and there is no meaning to picking two.
//
// The choice applies to the LAYER being edited. Set them on the base layer and every other
// layer inherits, which is how one set of profiles covers the whole keyboard; change one on
// another layer and only that layer differs. The flash works out that the board then needs the
// base layer's profiles plus that alternate.
export default function ModuleBayPicker({
  open, anchorLabel, layerLabel, profiles, selectedId, inherited, onPick, onClose, onManage,
}) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);

  // Close on an outside click or Escape, the way a native menu does.
  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open, onClose]);

  // The module row sits in a narrow centre column, so the menu is positioned against the
  // viewport rather than clipped inside it.
  useEffect(() => {
    if (!open || !ref.current) return;
    const host = ref.current.parentElement?.getBoundingClientRect();
    if (host) setPos({ top: host.bottom + 6, left: Math.max(8, host.left + host.width / 2 - 120) });
  }, [open]);

  if (!open) return null;
  return (
    <div className="bay-menu" ref={ref} style={pos ? { top: pos.top, left: pos.left } : undefined}>
      {/* Which LAYER this choice applies to. A bay assignment is per-layer -- the same Tune
          icon opens a different answer on every layer -- and the menu never said which one you
          were looking at, so two layers' menus were indistinguishable. */}
      <div className="bay-menu-head">
        <span className="bay-menu-mod">{anchorLabel}</span>
        {layerLabel && <span className="bay-menu-layer">{layerLabel}</span>}
      </div>
      {profiles.length === 0 ? (
        <div className="bay-menu-empty">No profiles for this module yet.</div>
      ) : (
        profiles.map((p) => (
          <button key={p.id} className={"bay-menu-item" + (p.id === selectedId ? " on" : "")}
            onClick={() => onPick(p.id)}>
            <span className="bay-radio">{p.id === selectedId ? "◉" : "○"}</span>
            <span className="bay-menu-name">{p.name}</span>
            {p.onBoard && <span className="bay-tag" title="Running on the keyboard">live</span>}
          </button>
        ))
      )}
      {inherited && (
        <div className="bay-menu-note">
          Inherited from the base layer. Picking here overrides it for this layer only.
        </div>
      )}
      <div className="bay-menu-sep" />
      <button className="bay-menu-item subtle" onClick={() => onPick("disabled")}>
        <span className="bay-radio">{selectedId === "disabled" ? "◉" : "○"}</span>
        <span className="bay-menu-name">Disabled on this layer</span>
      </button>
      {onManage && (
        <button className="bay-menu-item subtle" onClick={() => { onManage(); onClose(); }}>
          <span className="bay-radio" />
          <span className="bay-menu-name">Edit profiles…</span>
        </button>
      )}
    </div>
  );
}
