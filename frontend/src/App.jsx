import { useEffect } from "react";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { hydrateDeviceState, invalidateDeviceState } from "./lib/deviceState";
import { api } from "./lib/api";
import { applyInterfaceScaling, scalingFromSettings } from "./lib/scaling";
import { useDeviceStream } from "./lib/deviceStream";
import DeviceChip from "./components/DeviceChip";
import DialogHost from "./components/ui/ConfirmDialog";
import Hub from "./pages/Hub.jsx";
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
  // Device Manager left the nav on 2026-09-11 and the code on 2026-09-17: its halves, its
  // lighting buttons and its live status all live on Information (Device / Connections /
  // Troubleshooting) and in the chip below the brand. The route redirects so a saved link
  // still lands somewhere useful.
  { to: "/information", label: "Information" },
  { to: "/settings", label: "Settings" },
];

function Sidebar() {
  const { data, connected } = useDeviceStream();
  // If we lose the backend we can no longer vouch for what is on the keyboard.
  useEffect(() => {
    if (!connected) invalidateDeviceState("disconnected");
  }, [connected]);
  // Seed from the last read the backend recorded, so a reload does not drop the live marks.
  // It is a belief with a timestamp, not a claim about the board right now -- see deviceState.
  useEffect(() => { hydrateDeviceState(api); }, []);
  return (
    <nav className="sidebar">
      <div className="brand">
        <span className="brand-dot" />
        OpenFlow
      </div>
      <DeviceChip status={data?.status} />
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
        >
          {item.label}
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

function RouteBoundary({ children }) {
  const { pathname } = useLocation();
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>;
}


export default function App() {
  // Apply the saved interface scaling once at startup, before anything renders at the wrong size.
  // Live changes are applied by the Settings page as the slider moves; this is the on-load pass.
  useEffect(() => {
    api.settings().then((s) => {
      const v = scalingFromSettings(s);
      if (v !== null) applyInterfaceScaling(v);
    }).catch(() => {});
  }, []);
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        {/* Keyed on the path so navigating away from a crashed page RESETS the boundary --
            otherwise one bad page would keep showing its error after you had moved on. The
            sidebar stays mounted outside it, so there is always a way out. */}
        <RouteBoundary>
        <Routes>
          <Route path="/" element={<Hub />} />
          <Route path="/device-management" element={<Navigate to="/information" replace />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/layer-management" element={<Bindings />} />
          <Route path="/colormapping" element={<Color />} />
          <Route path="/macro" element={<Macros />} />
          <Route path="/module-configuration" element={<Modules />} />
          <Route path="/information" element={<Troubleshooting />} />
          <Route path="/bug-report" element={<Placeholder title="Bug Report" phase="Phase 1" note="Diagnostics report export." />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </RouteBoundary>
      </main>
      {/* One host for every confirmDialog() in the app; see lib/dialogs.js. */}
      <DialogHost />
    </div>
  );
}
