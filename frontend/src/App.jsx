import { useEffect } from "react";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./lib/api";
import { applyInterfaceScaling, scalingFromSettings } from "./lib/scaling";
import DialogHost from "./components/ui/ConfirmDialog";
import ProfileBar from "./components/shell/ProfileBar";
import TopNav from "./components/shell/TopNav";
import Hub from "./pages/Hub.jsx";
import Troubleshooting from "./pages/Troubleshooting.jsx";
import Settings from "./pages/Settings.jsx";
import Placeholder from "./pages/Placeholder.jsx";
import Bindings from "./pages/Bindings.jsx";
import Color from "./pages/Color.jsx";
import Modules from "./pages/Modules.jsx";
import Macros from "./pages/Macros.jsx";
import BugReport from "./pages/BugReport.jsx";

function RouteBoundary({ children }) {
  const { pathname } = useLocation();
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>;
}

// The shell: the top nav, the persistent profile bar, and the page. The routes mirror the
// recovered NayaFlow renderer and are left alone (see components/shell/TopNav for the labels).
// Device Manager left the nav on 2026-09-11 and the code on 2026-09-17: its halves, its
// lighting buttons and its live status all live on Information (Device / Connections /
// Troubleshooting) and in the profile bar. The route redirects so a saved link still lands
// somewhere useful.
export default function App() {
  // The Hub is the front door: the nav stays (it is how you leave), the profile bar does not.
  // Its halves duplicate the Hub's Keyboard card and Read / Back up / Flash have nothing to
  // act on there; it mounts on the first editing page (owner's call, 2026-09-17).
  const { pathname } = useLocation();
  const onHub = pathname === "/";
  // Where the user was before opening the report form, so the report can say which page the
  // problem was on. Recorded here because by the time that page unmounts it is too late.
  useEffect(() => {
    if (pathname === "/bug-report") return;
    try { sessionStorage.setItem("openflow.lastPage", pathname); } catch { /* private mode */ }
  }, [pathname]);
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
      <TopNav />
      {!onHub && <ProfileBar />}
      <main className="main">
        {/* Keyed on the path so navigating away from a crashed page RESETS the boundary --
            otherwise one bad page would keep showing its error after you had moved on. The
            nav and the bar stay mounted outside it, so there is always a way out. */}
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
          <Route path="/bug-report" element={<BugReport />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </RouteBoundary>
      </main>
      {/* One host for every confirmDialog() in the app; see lib/dialogs.js. */}
      <DialogHost />
    </div>
  );
}
