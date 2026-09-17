import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import ThemeToggle from "./ThemeToggle";

// The top navigation: the logo (to the Hub), the pages, a More menu, the Settings gear, the
// theme switch.
//
// Ordered by how often a page is reached for, not by how it was built: the three that shape
// what the keyboard DOES (bindings, LEDs, modules) come first and together, then macros, then
// the device page. The routes are NayaFlow's own and are left alone -- renaming a label is
// free ("Devices" is the Information page), renaming a URL breaks every link anyone has saved.
export const NAV = [
  { to: "/layer-management", label: "Bindings" },
  { to: "/colormapping", label: "LED Map" },
  { to: "/module-configuration", label: "Modules" },
  { to: "/macro", label: "Macros" },
  { to: "/information", label: "Devices" },
];

// Under More: the pages that are about the app rather than the keyboard. Settings is not
// one of them: it has its own gear beside the menu (owner's call, 2026-09-17).
export const MORE = [
  { to: "/", label: "Hub", end: true },
  { to: "/bug-report", label: "Bug Report" },
];

const linkClass = ({ isActive }) => "nav-item" + (isActive ? " active" : "");

export default function TopNav() {
  const [open, setOpen] = useState(false);
  const moreRef = useRef(null);
  const { pathname } = useLocation();

  // The menu closes when a page is chosen, on a click anywhere else, and on Escape.
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return undefined;
    function onDoc(e) {
      if (moreRef.current && !moreRef.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const moreActive = MORE.some((m) => (m.end ? pathname === m.to : pathname.startsWith(m.to)));

  return (
    <nav className="shell-nav" aria-label="Main">
      <NavLink to="/" end className="brand" title="Hub">
        <span className="brand-dot" />
        OpenFlow
      </NavLink>
      {NAV.map((item) => (
        <NavLink key={item.to} to={item.to} className={linkClass}>
          {item.label}
        </NavLink>
      ))}
      <div className="shell-nav-spacer" />
      <div className="shell-nav-more" ref={moreRef}>
        <button
          type="button"
          className={"nav-item" + (moreActive ? " active" : "")}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          More ▾
        </button>
        {open && (
          <div className="shell-nav-menu" role="menu" aria-label="More">
            {MORE.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} role="menuitem" className={linkClass}>
                {item.label}
              </NavLink>
            ))}
          </div>
        )}
      </div>
      <NavLink to="/settings" className={({ isActive }) => "shell-gear" + (isActive ? " active" : "")}
        title="Settings" aria-label="Settings">
        ⚙
      </NavLink>
      <ThemeToggle />
    </nav>
  );
}
