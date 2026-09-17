// Every route renders, in both themes, with no page error and no console error, and leaves a
// screenshot under tests/e2e/shots/<theme>/<page>.png for a by-eye comparison (nothing asserts
// pixels: fonts, DPI and zoom would make that a maintenance sink). The theme is set the way the
// app will read it once the token work lands (localStorage openflow.theme + data-theme); before
// that it is inert, so both sets look the same. /rpc/flash is aborted at the page unless
// OPENFLOW_E2E_DEVICE=1, and the backend's confirm gate is the second lock.
import { test, expect } from "@playwright/test";
import { E2E_BACKEND_PORT } from "./env.js";

const PAGES = [
  ["hub", "/"],
  ["bindings", "/layer-management"],
  ["led-map", "/colormapping"],
  ["modules", "/module-configuration"],
  ["macros", "/macro"],
  ["information", "/information"],
  ["settings", "/settings"],
  ["device-management", "/device-management"],
];
const THEMES = ["dark", "light"];

for (const theme of THEMES) {
  for (const [name, route] of PAGES) {
    test(`${name} renders in ${theme}`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });
      await page.addInitScript(([port, t]) => {
        window.EXPOSED = { bgServerPort: port };
        try { localStorage.setItem("openflow.theme", t); } catch {}
        // The init script can run before the document exists; the attribute is only a hint
        // until the theme work lands (the pre-paint script will read localStorage itself).
        const apply = () => { if (document.documentElement) document.documentElement.dataset.theme = t; };
        apply();
        document.addEventListener("DOMContentLoaded", apply);
      }, [E2E_BACKEND_PORT, theme]);
      if (!process.env.OPENFLOW_E2E_DEVICE) {
        await page.route("**/rpc/flash", (r) => r.abort());
      }
      await page.goto(`/#${route}`);
      await expect(page.locator("main")).toBeVisible();
      // The SSE stream keeps a request open, so "networkidle" never comes; settle by time.
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `tests/e2e/shots/${theme}/${name}.png` });
      expect(errors, `${name} (${theme}) logged errors`).toEqual([]);
    });
  }
}
