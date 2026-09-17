// Where the route walk's own backend lives: its port, the python that runs it, and the scratch
// data directory it is seeded into. Shared by playwright.config.js, backend.mjs and the specs.
// No side effects here: this module is loaded by every Playwright process.
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const FRONTEND_DIR = resolve(here, "../..");
export const BACKEND_DIR = resolve(FRONTEND_DIR, "../backend");
export const DATA_DIR = resolve(here, ".data");
export const E2E_BACKEND_PORT = 3011;

const venvPython = resolve(BACKEND_DIR, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
export const PYTHON = process.env.OPENFLOW_PYTHON || (existsSync(venvPython) ? venvPython : "python");
