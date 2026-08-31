// Layer selector — the top-left panel from NayaFlow: profile name + ordered
// layers with the active one highlighted.
export default function LayerList({ profile, layers, activeLayerId, onSelect }) {
  return (
    <div className="layer-list">
      <div className="layer-profile">
        <span className="layer-profile-dot" />
        {profile?.name || "Profile"}
      </div>
      {layers.map((l, i) => (
        <button
          key={l.id}
          className={"layer-item" + (l.id === activeLayerId ? " active" : "")}
          onClick={() => onSelect(l.id)}
        >
          <span className="layer-index">{i}</span>
          <span className="layer-name">{l.name}</span>
        </button>
      ))}
    </div>
  );
}
