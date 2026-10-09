// The README's screenshots, regenerated on demand against the route walk's own backend (seeded
// from the stock profile, so a real keymap shows): Bindings with a key selected, the LED Map, and
// a Tune's scroll gesture selected, each in both themes, written to ../docs/media/. Skipped unless asked for:
//
//     README_SHOTS=1 npx playwright test tests/e2e/readme-shots.spec.js
import { test, expect } from "@playwright/test";
import { E2E_BACKEND_PORT } from "./env.js";

test.skip(!process.env.README_SHOTS, "README screenshots run only when README_SHOTS=1");

const OUT = "../docs/media";

for (const theme of ["dark", "light"]) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript(([port, t]) => {
        window.EXPOSED = { bgServerPort: port };
        try { localStorage.setItem("openflow.theme", t); } catch {}
        const apply = () => { if (document.documentElement) document.documentElement.dataset.theme = t; };
        apply();
        document.addEventListener("DOMContentLoaded", apply);
      }, [E2E_BACKEND_PORT, theme]);
      await page.route("**/rpc/flash", (r) => r.abort());
    });

    test(`bindings (${theme})`, async ({ page }) => {
      await page.goto("/#/layer-management");
      await expect(page.getByText("Typing").first()).toBeVisible();
      // The board's keys draw their legends, so they carry no text: pos 0 is the top-left key,
      // Esc on the stock profile.
      await page.locator('button.kc[title="pos 0"]').click();
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${OUT}/bindings-${theme}.png` });
    });

    test(`led map (${theme})`, async ({ page }) => {
      await page.goto("/#/colormapping");
      await expect(page.getByText("LED Mapping Tools")).toBeVisible();
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${OUT}/led-map-${theme}.png` });
    });

    test(`modules (${theme})`, async ({ page }) => {
      await page.goto("/#/module-configuration");
      await page.getByText("Naya Tune Mac/Win").click();
      await page.waitForTimeout(600);
      await page.getByText("Vertical Scroll", { exact: true }).first().click();
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${OUT}/modules-${theme}.png` });
    });
  });
}
