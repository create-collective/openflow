import { setThemePreference, useResolvedTheme } from "../../lib/theme";

// The light / dark switch in the top nav, as the storyboard draws it: a pill with the sun at
// one end and the moon at the other, the knob on the side that is on. It sets an explicit
// preference (the theme follows the OS until the switch is used, and the choice is remembered);
// Settings > Interface is where "system" can be chosen again. A real switch for assistive
// tech: role switch, checked when dark.
export default function ThemeToggle() {
  const theme = useResolvedTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark theme"
      title={dark ? "Switch to the light theme" : "Switch to the dark theme"}
      className={"shell-theme" + (dark ? " on" : "")}
      onClick={() => setThemePreference(dark ? "light" : "dark")}
    >
      <svg className="shell-theme-sun" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"
        fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" />
      </svg>
      <svg className="shell-theme-moon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"
        fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
      </svg>
      <span className="shell-theme-knob" aria-hidden="true" />
    </button>
  );
}
