import { useEffect } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { hydrateDeviceState, invalidateDeviceState } from "./lib/deviceState";
import { api } from "./lib/api";
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
// Ordered by how often a page is reached for, not by how it was built: the three that shape
// what the keyboard DOES (bindings, LEDs, modules) come first and together, then macros, then
// the device and app pages. The routes are NayaFlow's own and are left alone -- renaming a
// label is free, renaming a URL breaks every link anyone has saved.
const NAV = [
  { to: "/", label: "Hub", end: true },
  { to: "/layer-management", label: "Bindings" },
  { to: "/colormapping", label: "LED Map" },
  { to: "/module-configuration", label: "Modules" },
  { to: "/macro", label: "Macros" },
  { to: "/device-management", label: "Device Manager" },
  { to: "/information", label: "Information" },
  { to: "/settings", label: "Settings" },
];

function Sidebar() {
  const { data, connected } = useSSE("sse:naya-devices-stream");
  // If we lose the backend we can no longer vouch for what is on the keyboard.
  useEffect(() => {
    if (!connected) invalidateDeviceState("disconnected");
  }, [connected]);
  // Seed from the last read the backend recorded, so a reload does not drop the live marks.
  // It is a belief with a timestamp, not a claim about the board right now -- see deviceState.
  useEffect(() => { hydrateDeviceState(api); }, []);
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
