import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useSSE } from "./lib/useSSE";
import Hub from "./pages/Hub.jsx";
import DeviceManagement from "./pages/DeviceManagement.jsx";
import Troubleshooting from "./pages/Troubleshooting.jsx";
import Settings from "./pages/Settings.jsx";
import Placeholder from "./pages/Placeholder.jsx";
import Bindings from "./pages/Bindings.jsx";
import Color from "./pages/Color.jsx";
import Modules from "./pages/Modules.jsx";
import Macros from "./pages/Macros.jsx";

// Routes mirror the recovered NayaFlow renderer.
const NAV = [
  { to: "/", label: "Hub", end: true },
  { to: "/layer-management", label: "Bindings" },
  { to: "/colormapping", label: "Color" },
  { to: "/macro", label: "Macros" },
  { to: "/module-configuration", label: "Modules" },
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
          <Route path="/layer-management" element={<Bindings />} />
          <Route path="/colormapping" element={<Color />} />
          <Route path="/macro" element={<Macros />} />
          <Route path="/module-configuration" element={<Modules />} />
          <Route path="/information" element={<Troubleshooting />} />
          <Route path="/bug-report" element={<Placeholder title="Bug Report" phase="Phase 1" note="Diagnostics report export." />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
