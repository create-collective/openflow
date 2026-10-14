// Two of the README's screenshots, regenerated on demand against the route walk's own backend
// (seeded from the stock profile, so a real keymap shows): the LED Map, and a Tune's scroll
// gesture selected on Modules, in the dark theme, written to ../docs/media/. The README's other
// pictures (the Hub, Bindings with a Create on USB, the GIF) are the owner's own captures.
// Skipped unless asked for:
//
//     README_SHOTS=1 npx playwright test tests/e2e/readme-shots.spec.js
import { test, expect } from "@playwright/test";
import { E2E_BACKEND_PORT } from "./env.js";

test.skip(!process.env.README_SHOTS, "README screenshots run only when README_SHOTS=1");

const OUT = "../docs/media";
const THEME = "dark";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(([port, t]) => {
    window.EXPOSED = { bgServerPort: port };
    try { localStorage.setItem("openflow.theme", t); } catch {}
    const apply = () => { if (document.documentElement) document.documentElement.dataset.theme = t; };
    apply();
    document.addEventListener("DOMContentLoaded", apply);
  }, [E2E_BACKEND_PORT, THEME]);
  await page.route("**/rpc/flash", (r) => r.abort());
});

test("led map", async ({ page }) => {
  await page.goto("/#/colormapping");
  await expect(page.getByText("LED Mapping Tools")).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/led-map-${THEME}.png` });
});

test("modules", async ({ page }) => {
  await page.goto("/#/module-configuration");
  await page.getByText("Naya Tune Mac/Win").click();
  await page.waitForTimeout(600);
  await page.getByText("Vertical Scroll", { exact: true }).first().click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/modules-${THEME}.png` });
});
