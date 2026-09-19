import Badge from "./ui/Badge";

// The module profiles a keyboard profile carries, one row per bay, under the layer list.
//
// A read finds them and a flash writes them, but until now the only place that said WHICH
// profile each bay would get was the "live" tag inside the bay pickers on the board. This
// lists them for the layer being edited: the slot, the profile's name, whether the board is
// running it (live), and whether the layer inherits it from the base layer (a dim "base"
// after the slot, so the row never changes shape). A row outlined in the accent names a
// profile the board does NOT have yet: the next flash writes it. What is physically docked is
// the profile bar's business. It follows the four bay icons on the board as they change.
// Clicking a row opens that profile on the Modules page.
const SLOTS = [
  { type: "track", side: "left", label: "Track L" },
  { type: "track", side: "right", label: "Track R" },
  { type: "touch", side: null, label: "Touch" },
  { type: "tune", side: null, label: "Tune" },
];

// This row is a PROFILE, not a docked position: for Touch and Tune one control governs both
// bays, so there is no side to draw. The right-hand Touch is named explicitly as the generic
// depiction rather than inheriting a file called touch.png that silently meant one side.
const moduleImg = (type, side) =>
  type === "track" ? `/modules/v2/track-${side === "right" ? "right" : "left"}.png`
    : type === "touch" ? "/modules/v2/touch-right.png"
      : `/modules/v2/${type}.png`;

export default function ModuleProfileList({ bays, boardKnown = false }) {
  if (!bays) return null;
  return (
    <div className="modprof" aria-label="Module profiles">
      <div className="layer-title">Module profiles</div>
      <div className="modprof-sub">{bays.layerLabel ? `For ${bays.layerLabel}` : "Per layer"}</div>
      {SLOTS.map((s) => {
        const sel = bays.selectedFor(s.type, s.side);
        const entry = sel && sel !== "disabled" ? bays.profilesFor(s.type, s.side).find((p) => p.id === sel) : null;
        const inherited = bays.inheritedFor(s.type, s.side);
        // The left and right bays disagree, which one row cannot show. Saying it beats
        // picking a side silently, because the next pick writes to both (SCRUM-92).
        const split = bays.splitFor?.(s.type, s.side) || false;
        const name = sel === "disabled" ? "Disabled" : entry ? entry.name : sel ? "Unknown profile" : "Not set";
        const unset = !entry;
        // Only once the board has been read can "not on it" mean anything.
        const pending = boardKnown && !!entry && !entry.onBoard;
        return (
          <button
            key={s.label}
            type="button"
            className={"modprof-row" + (entry?.onBoard ? " live" : "") + (pending ? " pending" : "")}
            title={`${s.label}: ${name}.${pending ? " Not on the board yet: the next flash writes it." : ""}${split ? " The left and right bays currently differ; choosing here sets both." : ""} Open on the Modules page.`}
            onClick={() => bays.onManage(s.type, s.side)}
          >
            <img className="modprof-img" src={moduleImg(s.type, s.side)} alt="" />
            <span className="modprof-text">
              <span className="modprof-head">
                <span className="modprof-slot">
                  {s.label}
                  {inherited && <span className="modprof-inherit" title="From the base layer"> · base</span>}
                </span>
                {entry?.onBoard && <Badge tone="ok" size="xs">live</Badge>}
                {split && <Badge tone="warn" size="xs">sides differ</Badge>}
              </span>
              <span className={"modprof-name" + (unset ? " unset" : "")}>{name}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
