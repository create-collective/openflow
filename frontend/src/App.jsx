import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useSSE } from "./lib/useSSE";
import Hub from "./pages/Hub.jsx";
import DeviceManagement from "./pages/DeviceManagement.jsx";
import Troubleshooting from "./pages/Troubleshooting.jsx";
import Settings from "./pages/Settings.jsx";
import Placeholder from "./pages/Placeholder.jsx";

// Routes mirror the recovered NayaFlow renderer.
const NAV = [
  { to: "/", label: "Hub", end: true },
  { to: "/layer-management", label: "Bindings", phase: 2 },
  { to: "/colormapping", label: "Color", phase: 2 },
  { to: "/macro", label: "Macros", phase: 2 },
  { to: "/module-configuration", label: "Modules", phase: 2 },
  { to: "/device-management", label: "Device Manager" },
  { to: "/information", label: "Information" },
  { to: "/settings", label: "Settings" },
];

function Sidebar() {
  const { data, connected } = useSSE("sse:naya-devices-stream");
  const deviceCount = data?.devices?.length ?? 0;
  return (
    <nav className="sidebar">
      <div className="brand">
        <span className="brand-dot" />
        OpenFlow
      </div>
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
        >
          {item.label}
          {item.phase === 2 && <span className="badge">soon</span>}
          {item.to === "/device-management" && deviceCount > 0 && (
            <span className="badge">{deviceCount}</span>
          )}
        </NavLink>
      ))}
      <div className="nav-spacer" />
      <div className="nav-item" style={{ pointerEvents: "none" }}>
        <span className={"dot " + (connected ? "ok" : "err")} />
        {connected ? "Backend connected" : "Backend offline"}
      </div>
    </nav>
  );
}

export default function App() {
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Hub />} />
          <Route path="/device-management" element={<DeviceManagement />} />
          <Route path="/settings" element={<Settings />} />
          <Route
            path="/layer-management"
            element={
              <Placeholder
                title="Bindings"
                phase="Phase 2"
                note="The keymap / layer editor. Requires the REMAP protocol (category 0x30) to be implemented — the opcodes are documented but the payload format is not yet reverse-engineered. This is the core product and the main Phase 2 deliverable."
              />
            }
          />
          <Route
            path="/colormapping"
            element={
              <Placeholder
                title="Color"
                phase="Phase 2"
                note="Per-key LED color mapping (brush/fill/pipette/palette). Depends on REMAP LED MAP DATA (0x30/0x100D-0x100E)."
              />
            }
          />
          <Route
            path="/macro"
            element={
              <Placeholder
                title="Macros"
                phase="Phase 2"
                note="Macro editor (standard/mouse/text/wait/loop steps). Depends on REMAP MACRO LIST/DATA (0x30/0x1005-0x1008)."
              />
            }
          />
          <Route
            path="/module-configuration"
            element={
              <Placeholder
                title="Modules"
                phase="Phase 2"
                note="Touch / Track / Tune / Float module configuration. Depends on REMAP MODULE CONFIG (0x30/0x1009-0x100C)."
              />
            }
          />
          <Route path="/information" element={<Troubleshooting />} />
          <Route path="/bug-report" element={<Placeholder title="Bug Report" phase="Phase 1" note="Diagnostics report export." />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
