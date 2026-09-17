// Build the backend sidecar with PyInstaller: backend/dist/openflow-backend/.
//
// Uses the backend venv's python when there is one (the developer's machine), else `python` on
// PATH (CI, where the backend was pip-installed with its build extra). Needs a built frontend:
// the spec bundles frontend/dist as the renderer and refuses to run without it.
//
//     npm run build:sidecar          (after npm run build:frontend)
//     OPENFLOW_PYTHON=/path/to/python overrides the interpreter
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BACKEND = resolve(ROOT, "backend");
const venv = resolve(BACKEND, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const python = process.env.OPENFLOW_PYTHON || (existsSync(venv) ? venv : "python");

if (!existsSync(resolve(ROOT, "frontend/dist/index.html"))) {
  console.error("build-sidecar: frontend/dist/index.html is missing; run `npm run build:frontend` first");
  process.exit(1);
}

console.log(`build-sidecar: ${python} -m PyInstaller openflow_backend.spec (in ${BACKEND})`);
const r = spawnSync(python, ["-m", "PyInstaller", "openflow_backend.spec", "--noconfirm"], {
  cwd: BACKEND,
  stdio: "inherit",
});
if (r.status !== 0) {
  console.error(`build-sidecar: PyInstaller exited ${r.status ?? r.signal}`);
  process.exit(r.status ?? 1);
}
const exe = resolve(BACKEND, "dist/openflow-backend", process.platform === "win32" ? "openflow-backend.exe" : "openflow-backend");
if (!existsSync(exe)) {
  console.error(`build-sidecar: expected ${exe} after the build`);
  process.exit(1);
}
console.log(`build-sidecar: ${exe}`);
