// The route walk's backend: wipe the scratch data directory, seed it from the snapshot that
// ships with the repository, then serve on the e2e port until Playwright stops us. One process
// from Playwright's point of view (it kills the tree on shutdown); the seed runs to completion
// first so the server never opens an empty database. Kept out of playwright.config.js on
// purpose: that file is evaluated by every worker, and a wipe there ran mid-test.
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { BACKEND_DIR, DATA_DIR, E2E_BACKEND_PORT, PYTHON } from "./env.js";

rmSync(DATA_DIR, { recursive: true, force: true });
mkdirSync(DATA_DIR, { recursive: true });
const env = { ...process.env, OPENFLOW_DATA_DIR: DATA_DIR };

const seed = spawnSync(PYTHON, ["-m", "openflow_backend.seed", "--force"], { cwd: BACKEND_DIR, env, stdio: "inherit" });
if (seed.status !== 0) {
  console.error(`[e2e] seeding failed (exit ${seed.status})`);
  process.exit(seed.status ?? 1);
}

const server = spawn(PYTHON, ["-m", "openflow_backend", String(E2E_BACKEND_PORT)], { cwd: BACKEND_DIR, env, stdio: "inherit" });
server.on("exit", (code) => process.exit(code ?? 0));
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => server.kill());
