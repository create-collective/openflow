// The theme preference: system | light | dark.
//
// Kept in localStorage ("openflow.theme") and applied as data-theme on <html>, which is what
// theme.css switches on. index.html applies the same rule before first paint so there is never
// a flash of the wrong theme; this module keeps it in step afterwards (the setting control, and
// the OS switching while the preference is "system") and exposes it to React through
// useSyncExternalStore, the same external-store shape as deviceState.js. Nothing here talks to
// the backend: the preference belongs to this machine, like the window size.
import { useSyncExternalStore } from "react";

const KEY = "openflow.theme";
export const THEME_PREFERENCES = ["system", "light", "dark"];

const listeners = new Set();

function read() {
  try {
    const v = localStorage.getItem(KEY);
    return THEME_PREFERENCES.includes(v) ? v : "system";
  } catch {
    return "system";
  }
}

function systemTheme() {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "dark";
  }
}

let pref = read();

/** "light" or "dark": what is actually on screen for a preference (default: the current one). */
export function resolvedTheme(p = pref) {
  return p === "system" ? systemTheme() : p;
}

function apply() {
  document.documentElement.dataset.theme = resolvedTheme();
}

function emit() {
  for (const l of listeners) l();
}

export function getThemePreference() {
  return pref;
}

export function setThemePreference(next) {
  pref = THEME_PREFERENCES.includes(next) ? next : "system";
  try { localStorage.setItem(KEY, pref); } catch {}
  apply();
  emit();
}

export function subscribeTheme(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The stored preference (system | light | dark), live. */
export function useThemePreference() {
  return useSyncExternalStore(subscribeTheme, getThemePreference, () => "system");
}

/** What is on screen (light | dark), live: follows the OS while the preference is "system". */
export function useResolvedTheme() {
  return useSyncExternalStore(subscribeTheme, () => resolvedTheme(), () => "dark");
}

try {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (pref === "system") { apply(); emit(); }
  });
} catch {}

apply();
