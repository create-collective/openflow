import { useState } from "react";
import Button from "./ui/Button";

// The left column of Bindings and LED Map (layers, module profiles), which can fold into a thin
// strip so the board gets its width. The board is drawn at one size and scaled to the room
// beside this column (BoardFit), so on a window narrower than board + column -- a laptop at
// 175-200% display scaling -- the column is what the board is losing to, and Interface scaling
// only makes the column wider. Folding it is the user's call and is remembered per computer.
// The contents stay mounted while folded, so the layer list keeps its state.
const KEY = "openflow.railCollapsed";

function readCollapsed() {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export default function RailColumn({ children }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem(KEY, next ? "1" : "0"); } catch { /* private mode */ }
  };
  return (
    <div className={"layer-col" + (collapsed ? " collapsed" : "")}>
      <Button size="xs" variant="secondary" className="rail-toggle" onClick={toggle}
        aria-expanded={!collapsed}
        title={collapsed ? "Show layers and module profiles" : "Hide this column to give the board more room"}>
        {collapsed ? "»" : "« Hide"}
      </Button>
      <div className="rail-body" hidden={collapsed}>{children}</div>
    </div>
  );
}
