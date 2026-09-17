import Badge from "../components/ui/Badge";
import Card from "../components/ui/Card";
import Notice from "../components/ui/Notice";

export default function Placeholder({ title, phase, note }) {
  return (
    <div>
      <h1 className="page-title">
        {title} <Badge>{phase}</Badge>
      </h1>
      <p className="page-sub">This page is scaffolded but not yet implemented.</p>
      <Card>
        <Notice>{note}</Notice>
      </Card>
    </div>
  );
}
