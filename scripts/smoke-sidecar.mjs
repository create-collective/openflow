// Smoke-test the frozen sidecar: start it, prove every bundled resource is reachable, stop it.
//
// No hardware needed; the only /rpc route it touches is the token-guarded shutdown. Runs after
// every PyInstaller build (npm run build:app chains it) and on all three CI runners, so a
// missing hidden import, a data file left out of the spec, or a resolver that walks up from a
// source path fails here and not on a user's machine.
//
//     npm run smoke:sidecar                          backend/dist/openflow-backend/openflow-backend[.exe]
//     node scripts/smoke-sidecar.mjs <path-to-exe>   a specific build
//     --device                                       also expect a connected keyboard half
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const wantDevice = args.includes("--device");
const exe = args.find((a) => !a.startsWith("--"))
  || resolve(ROOT, "backend/dist/openflow-backend", process.platform === "win32" ? "openflow-backend.exe" : "openflow-backend");
const expectedVersion = readFileSync(resolve(ROOT, "backend/openflow_backend/__init__.py"), "utf8").match(/__version__\s*=\s*"([^"]+)"/)[1];

if (!existsSync(exe)) {
  console.error(`smoke-sidecar: ${exe} does not exist; run npm run build:sidecar first`);
  process.exit(1);
}

const freePort = () => new Promise((ok, fail) => {
  const s = createServer();
  s.unref();
  s.on("error", fail);
  s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => ok(port)); });
});

const dataDir = mkdtempSync(join(tmpdir(), "openflow-smoke-"));
const port = await freePort();
const base = `http://127.0.0.1:${port}`;
const INSTANCE = "smoke";
let output = "";
const child = spawn(exe, [String(port)], {
  cwd: dirname(exe),
  env: { ...process.env, OPENFLOW_DATA_DIR: dataDir, OPENFLOW_INSTANCE: INSTANCE },
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});
child.stdout.on("data", (d) => { output += d; });
child.stderr.on("data", (d) => { output += d; });
let exited = null;
child.on("exit", (code, signal) => { exited = { code, signal }; });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
const check = (label, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? `  (${detail})` : ""}`);
  if (!ok) failures.push(label);
};
const getJson = async (path) => {
  const r = await fetch(base + path);
  return { status: r.status, json: await r.json().catch(() => null), headers: r.headers };
};

try {
  // Readiness: the shell polls the same way, accepting only its own instance.
  let info = null;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline && !exited) {
    try {
      const r = await getJson("/api/info/system");
      if (r.status === 200 && r.json?.app === "OpenFlow") { info = r.json; break; }
    } catch {}
    await sleep(250);
  }
  check("answers /api/info/system within 30 s", !!info, exited ? `exited early: ${JSON.stringify(exited)}` : "");
  if (!info) throw new Error("no readiness");
  check("echoes the instance token", info.instance === INSTANCE, `instance=${info.instance}`);
  check("reports frozen=true", info.frozen === true);
  check(`backendVersion is ${expectedVersion}`, info.backendVersion === expectedVersion, `got ${info.backendVersion}`);

  const index = await fetch(base + "/");
  const html = await index.text();
  check("/ serves the renderer's index.html", index.status === 200 && /id="root"/.test(html), `status ${index.status}`);
  check("index.html is not cacheable", index.headers.get("cache-control") === "no-cache");
  const asset = html.match(/\/assets\/[^"']+\.js/)?.[0];
  const assetRes = asset ? await fetch(base + asset) : null;
  check("the renderer's script bundle is served", !!assetRes && assetRes.status === 200, asset || "no /assets/*.js in index.html");

  const userdata = await getJson("/api/userdata");
  const profiles = Array.isArray(userdata.json) ? userdata.json : userdata.json?.profiles;
  check("first run seeded at least one profile", userdata.status === 200 && Array.isArray(profiles) && profiles.length > 0,
    `${profiles?.length ?? 0} profile(s); schema.sql via importlib.resources`);

  const actions = await getJson("/api/actions");
  const actionCount = Array.isArray(actions.json) ? actions.json.length : Object.keys(actions.json || {}).length;
  check("/api/actions is populated", actions.status === 200 && actionCount > 0, `${actionCount}`);

  const shortcuts = await getJson("/api/app-shortcuts");
  const apps = shortcuts.json?.apps ?? shortcuts.json;
  const appCount = Array.isArray(apps) ? apps.length : Object.keys(apps || {}).length;
  check("/api/app-shortcuts finds resources/reference", shortcuts.status === 200 && appCount > 0, `${appCount} apps`);

  const catalog = await getJson("/api/firmware-catalog");
  check("/api/firmware-catalog lists images", catalog.status === 200 && (catalog.json?.images?.length ?? 0) > 0,
    `${catalog.json?.images?.length ?? 0} images`);

  const devices = await getJson("/api/devices");
  check("/api/devices answers (pyserial backends loaded)", devices.status === 200 && Array.isArray(devices.json?.devices),
    `${devices.json?.devices?.length ?? 0} device(s)`);

  const status = await getJson("/api/status");
  check("/api/status answers", status.status === 200);
  if (wantDevice) {
    check("a keyboard half is connected", /"connected"\s*:\s*true/.test(JSON.stringify(status.json)));
  }

  const wrong = await fetch(base + "/rpc/shutdown", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ instance: "wrong" }) });
  check("shutdown refuses the wrong token", wrong.status === 403, `status ${wrong.status}`);
  const stop = await fetch(base + "/rpc/shutdown", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ instance: INSTANCE }) });
  check("shutdown accepts its token", stop.status === 200, `status ${stop.status}`);
  const stopDeadline = Date.now() + 5_000;
  while (!exited && Date.now() < stopDeadline) await sleep(100);
  check("exits within 5 s of shutdown", !!exited, exited ? `code ${exited.code}` : "still running");

  check("user-data.db exists in the data dir", existsSync(join(dataDir, "user-data.db")));
  const logPath = join(dataDir, "logs", "backend.log");
  const log = existsSync(logPath) ? readFileSync(logPath, "utf8") : "";
  check("logs/backend.log has the startup line", /Uvicorn running on/.test(log));
} catch (e) {
  failures.push(String(e));
  console.error(`smoke-sidecar: ${e}`);
} finally {
  if (!exited) {
    child.kill();
    await sleep(500);
  }
  try { rmSync(dataDir, { recursive: true, force: true }); } catch {}
}

if (failures.length) {
  console.error(`\nsmoke-sidecar: ${failures.length} check(s) failed. Sidecar output:\n${output.slice(-4000)}`);
  process.exit(1);
}
console.log(`\nsmoke-sidecar: all checks passed (${exe})`);
