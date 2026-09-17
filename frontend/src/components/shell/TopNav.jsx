import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import BrandMark from "../BrandMark";
import ThemeToggle from "./ThemeToggle";

// The top navigation: the logo (to the Hub), the pages, a More menu, the Settings gear, the
// theme switch.
//
// Ordered by how often a page is reached for, not by how it was built: the three that shape
// what the keyboard DOES (bindings, LEDs, modules) come first and together, then macros, then
// the device page. The routes are NayaFlow's own and are left alone -- renaming a label is
// free ("Devices" is the Information page), renaming a URL breaks every link anyone has saved.
export const NAV = [
  { to: "/layer-management", label: "Bindings", icon: "grid" },
  { to: "/colormapping", label: "LED Map", icon: "sun" },
  { to: "/module-configuration", label: "Modules", icon: "cube" },
  { to: "/macro", label: "Macros", icon: "play" },
  { to: "/information", label: "Devices", icon: "chip" },
];

// The glyph before each tab, as the storyboard draws them: a grid of keys, a sun, a cube, a
// play mark, a chip, and three dots for More. Strokes in the text colour, 16 px.
const GLYPH = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" /></>,
  cube: <><path d="M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z" /><path d="M3.5 7.25L12 12l8.5-4.75M12 12v9.5" /></>,
  play: <path d="M7 4.5v15l12-7.5z" />,
  chip: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>,
  more: <><circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none" /></>,
  // A gear that reads as one (Tabler Icons settings, MIT, Pawel Kuna).
  gear: <><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37c1 .608 2.296.07 2.572-1.065z" /><path d="M9 12a3 3 0 1 0 6 0a3 3 0 0 0-6 0" /></>,
};

function NavGlyph({ id }) {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {GLYPH[id]}
    </svg>
  );
}

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
      {/* The mark IS the O of OpenFlow, as the signature sheet sets it: mark, then penFlow. */}
      <NavLink to="/" end className="brand" title="Hub" aria-label="OpenFlow">
        <BrandMark size={24} className="brand-mark" />
        <span className="brand-word">penFlow</span>
      </NavLink>
      {NAV.map((item) => (
        <NavLink key={item.to} to={item.to} className={linkClass}>
          <NavGlyph id={item.icon} />
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
          <NavGlyph id="more" />
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
        <NavGlyph id="gear" />
      </NavLink>
      <ThemeToggle />
    </nav>
  );
}
