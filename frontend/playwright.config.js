// The route walk (tests/e2e): every page, both themes, no page errors, a screenshot each.
//
// It runs against its OWN backend on port 3011 (tests/e2e/backend.mjs) with a scratch data
// directory that is wiped and re-seeded from the repository snapshot on every run, so it never
// touches the owner's dev backend on 3001, its database, or the keyboard beyond the read-only
// status poll. The page is pointed at that backend through window.EXPOSED.bgServerPort, the same
// hook the Electron preload uses. The Vite dev server on 5173 is reused when one is running
// (local), started otherwise (CI). This file must stay free of side effects: every Playwright
// process evaluates it.
//
//     npm run e2e                 (playwright test)
//     OPENFLOW_E2E_DEVICE=1       allow /rpc/flash through (default: aborted at the page)
import { defineConfig } from "@playwright/test";
import { E2E_BACKEND_PORT } from "./tests/e2e/env.js";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 45_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    viewport: { width: 1600, height: 1000 },
  },
  webServer: [
    {
      command: "node tests/e2e/backend.mjs",
      url: `http://127.0.0.1:${E2E_BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
    },
  ],
});
