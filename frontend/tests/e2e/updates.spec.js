// OpenFlow's own updates as the desktop app shows them. The shell's half (electron/updater.js,
// window.openflowUpdates from the preload) is stubbed here, so every state the page can be in is
// reachable without a release: the once-only question, an update on offer, an install refused
// because a flash is running, and a copy that cannot replace itself. Screenshots land under
// tests/e2e/shots/updates/. The real check-download-install path is updater-e2e's job.
import { test, expect } from "@playwright/test";
import { E2E_BACKEND_PORT } from "./env.js";

// Installs the stub before the page loads. `calls` records what the page asked for.
async function withShell(page, { state, check, install }) {
  await page.addInitScript(([port, s, c, i]) => {
    window.EXPOSED = { bgServerPort: port };
    window.__calls = [];
    let current = { ...s };
    window.openflowUpdates = {
      state: async () => current,
      setCheck: async (on) => { window.__calls.push(["setCheck", on]); current = { ...current, check: on }; return true; },
      check: async () => { window.__calls.push(["check"]); return c; },
      install: async () => { window.__calls.push(["install"]); return i; },
      onProgress: () => () => {},
      onAvailable: () => () => {},
    };
  }, [E2E_BACKEND_PORT, state, check, install]);
}

const BASE = { current: "0.6.0", known: null, canInstall: true, unsupported: null,
  releasesUrl: "https://github.com/create-collective/openflow/releases/latest" };

test("the Hub asks once, and a yes turns on the weekly check", async ({ page }) => {
  await withShell(page, { state: { ...BASE, check: undefined } });
  await page.goto("/#/");
  const ask = page.getByText("Check for updates automatically, once a week?");
  await expect(ask).toBeVisible();
  await page.screenshot({ path: "tests/e2e/shots/updates/hub-question.png" });
  await page.getByRole("button", { name: "Yes", exact: true }).click();
  await expect(ask).toHaveCount(0);
  expect(await page.evaluate(() => window.__calls)).toContainEqual(["setCheck", true]);
});

test("an update the weekly check found is offered on the Hub, and refused during a flash", async ({ page }) => {
  await withShell(page, {
    state: { ...BASE, check: true, known: "9.9.9" },
    install: { blocked: "A firmware flash is running. Install the update once it has finished." },
  });
  await page.goto("/#/");
  await expect(page.getByText("Check for updates automatically, once a week?")).toHaveCount(0);
  const installButton = page.getByRole("button", { name: "Install 9.9.9 and restart" });
  await expect(installButton).toBeVisible();
  await installButton.click();
  await expect(page.getByText("A firmware flash is running.")).toBeVisible();
  await page.screenshot({ path: "tests/e2e/shots/updates/hub-blocked.png" });
});

test("Settings › About: the weekly switch, Check, the notes and Install", async ({ page }) => {
  await withShell(page, {
    state: { ...BASE, check: true },
    check: { current: "0.6.0", latest: "9.9.9", available: true,
      notes: "Updates from inside the app.\nSigned on Windows and macOS.", date: "2026-10-10" },
  });
  await page.goto("/#/settings?tab=about");
  await expect(page.getByLabel("Check for updates automatically, once a week")).toBeChecked();
  await page.getByRole("button", { name: /^check for updates$/i }).click();
  await expect(page.getByRole("button", { name: "Install 9.9.9 and restart" })).toBeVisible();
  await expect(page.getByText("Signed on Windows and macOS.")).toBeVisible();
  await page.screenshot({ path: "tests/e2e/shots/updates/settings-offer.png" });
});

test("a copy that cannot replace itself links to the release instead", async ({ page }) => {
  await withShell(page, {
    state: { ...BASE, check: true, known: "9.9.9", canInstall: false, unsupported: "the portable build" },
  });
  await page.goto("/#/settings?tab=about");
  await expect(page.getByRole("link", { name: /Download 9\.9\.9/ })).toBeVisible();
  await expect(page.getByText("This copy is the portable build, which cannot replace itself.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Install/ })).toHaveCount(0);
  await page.screenshot({ path: "tests/e2e/shots/updates/settings-portable.png" });
});
