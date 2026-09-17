import { setThemePreference, useResolvedTheme } from "../../lib/theme";
import IconButton from "../ui/IconButton";

// The light / dark switch in the top nav. It sets an explicit preference (the theme follows the
// OS until the switch is used, and the choice is remembered); Settings > Interface is where
// "system" can be chosen again.
export default function ThemeToggle() {
  const theme = useResolvedTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <IconButton className="shell-theme" title={`Switch to the ${next} theme`} onClick={() => setThemePreference(next)}>
      {theme === "dark" ? "☀" : "☾"}
    </IconButton>
  );
}
