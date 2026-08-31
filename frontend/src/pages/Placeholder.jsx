export default function Placeholder({ title, phase, note }) {
  return (
    <div>
      <h1 className="page-title">
        {title} <span className="pill">{phase}</span>
      </h1>
      <p className="page-sub">This page is scaffolded but not yet implemented.</p>
      <div className="card">
        <div className="phase-note">{note}</div>
      </div>
    </div>
  );
}
