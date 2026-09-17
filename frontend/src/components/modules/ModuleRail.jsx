import Button from "../ui/Button";
import IconButton from "../ui/IconButton";
import { TYPE_ORDER } from "../../lib/moduleLabels";

// The profile rail: add and import at the top, then every profile grouped by module type, with
// export / rename / delete revealed on hover. A module can hold several profiles and each layer
// picks one, so this manages a set rather than showing a fixed four. A profile the board is
// actually carrying reads brighter than one that only exists in the app.
export default function ModuleRail({
  grouped, variants, selectedId, onSelect,
  device, isLive, entryFor,
  adding, onToggleAdd, onAddProfile, importing, onImport,
  renaming, renameVal, onRenameChange, onStartRename, onCommitRename, onCancelRename,
  onExport, onRemove,
}) {
  return (
    <div className="module-list">
      <div className="module-list-head">
        <h1 className="module-list-title">Modules</h1>
        <p className="module-list-sub">Configure Touch, Track, and Tune modules.</p>
      </div>
      <div className="module-add">
        <Button size="sm" onClick={onToggleAdd}
          title="Add another profile for a module. A layer can use a different profile than the base layer, so more than one per module is useful.">
          + Add profile
        </Button>
        {adding && (
          <div className="module-add-menu">
            {variants.map((v) => (
              <button key={v.id} type="button" className="module-add-item" onClick={() => onAddProfile(v.id)}>
                {v.label}
                <span className="module-add-count">{v.bindings} binds</span>
              </button>
            ))}
            {variants.length === 0 && <div className="palette-disabled">No stock profiles found.</div>}
          </div>
        )}
        <Button size="sm" onClick={onImport} busy={importing}
          title="Import a module profile from a JSON file. The file names its own module type, so it lands under the right module.">
          {importing ? "Importing…" : "⭱  Import…"}
        </Button>
      </div>
      {TYPE_ORDER.map((type) =>
        grouped[type] ? (
          <div key={type} className="module-group">
            <div className="module-group-title">{type}</div>
            {grouped[type].map((m) => (
              renaming === m.id ? (
                <input
                  key={m.id}
                  className="module-rename"
                  autoFocus
                  value={renameVal}
                  onChange={(e) => onRenameChange(e.target.value)}
                  onBlur={onCommitRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onCommitRename();
                    if (e.key === "Escape") onCancelRename();
                  }}
                />
              ) : (
                <div key={m.id} className={"module-item-row ui-reveal-host" + (m.id === selectedId ? " active" : "")}>
                  <button
                    type="button"
                    className={"module-item" + (m.id === selectedId ? " active" : "")
                      + (device && isLive(m.id) ? " on-device" : "")}
                    onClick={() => onSelect(m.id)}
                    onDoubleClick={() => onStartRename(m)}
                    title={
                      !device
                        ? "Double-click to rename"
                        : isLive(m.id)
                        ? `Running on the keyboard as slot ${entryFor(m.id)?.slot}`
                        : entryFor(m.id)
                        ? "Edited since the last read — the keyboard is running something else"
                        : "Not on the keyboard — flash to put it there"
                    }
                  >
                    {/* The dot says whether the board runs this profile: green when live,
                        dim otherwise; the title says which. */}
                    <span className={"module-item-dot" + (device && isLive(m.id) ? " on" : "")} aria-hidden="true" />
                    <span className="module-item-name">{m.name}</span>
                  </button>
                  {/* The tools float over the tail of the row on hover rather than holding
                      space, so the name gets the whole width of the rail. */}
                  <span className="module-item-tools">
                    <IconButton reveal size="sm" title="Export this profile to a JSON file" onClick={() => onExport(m)}>⭳</IconButton>
                    <IconButton reveal size="sm" title="Rename" onClick={() => onStartRename(m)}>✎</IconButton>
                    <IconButton reveal size="sm" tone="danger" title="Delete this profile" onClick={() => onRemove(m)}>✕</IconButton>
                  </span>
                </div>
              )
            ))}
          </div>
        ) : null
      )}
    </div>
  );
}
