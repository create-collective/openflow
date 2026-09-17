// @vitest-environment node
// The frontend's side of the backend contract.
//
// backend/tests/route-manifest.json lists every route the FastAPI app serves (its own test keeps
// it honest). Here: every request src/lib/api.js makes is in that list; every `api.<name>(` a
// page calls is a real member of the api object (check-undefined cannot see member access, and
// `api.readKeybord` is exactly the typo a refactor produces); and no file but api.js talks to the
// backend, so the contract stays in one place. Pure text analysis: no server, no DOM.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const FRONTEND = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const SRC = join(FRONTEND, "src");
const API_FILE = join(SRC, "lib", "api.js");
const API = readFileSync(API_FILE, "utf8");
const MANIFEST = JSON.parse(
  readFileSync(join(FRONTEND, "..", "backend", "tests", "route-manifest.json"), "utf8"),
);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.jsx?$/.test(p)) out.push(p);
  }
  return out;
}

// Every request api.js makes, as { method, path } with the query string dropped and any
// template placeholder in the path itself turned into a route-parameter wildcard.
function requestsInApi() {
  const out = [];
  for (const m of API.matchAll(/req\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*(["'`])([^"'`]*)\2/g)) {
    out.push({ method: m[1], path: m[3] });
  }
  for (const m of API.matchAll(/fetch\(\s*BASE\s*\+\s*"([^"]+)"\s*,\s*\{\s*method:\s*"(\w+)"/g)) {
    out.push({ method: m[2], path: m[1] });
  }
  return out.map(({ method, path }) => ({ method, path: path.split("?")[0] }));
}

// "GET /api/x/{id}" and a request "/api/x/${id}" match on the wildcard.
function served(method, path) {
  const want = `${method} ${path}`;
  if (MANIFEST.includes(want)) return true;
  const re = new RegExp("^" + want.replace(/[.*+?^()|[\]\\]/g, "\\$&").replace(/\$\{[^}]*\}/g, "[^/]+") + "$");
  return MANIFEST.some((entry) => re.test(entry.replace(/\{[^}]+\}/g, "[^/]+")));
}

describe("api.js against the backend route manifest", () => {
  const requests = requestsInApi();

  it("finds the requests (the regexes still match api.js's shape)", () => {
    expect(requests.length).toBeGreaterThan(80);
  });

  it("only requests routes the backend serves", () => {
    const missing = requests.filter(({ method, path }) => !served(method, path)).map(({ method, path }) => `${method} ${path}`);
    expect(missing, "routes api.js calls that the backend does not serve").toEqual([]);
  });

  it("uses the device stream route", () => {
    expect(MANIFEST).toContain("GET /sse");
  });

  it("names only real api members from the pages", () => {
    const members = new Set([...API.matchAll(/^ {2}([A-Za-z_$][\w$]*)\s*:/gm)].map((m) => m[1]));
    expect(members.size).toBeGreaterThan(80);
    const unknown = [];
    for (const file of walk(SRC)) {
      if (file === API_FILE) continue;
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(/\bapi\.([A-Za-z_$][\w$]*)\s*\(/g)) {
        if (!members.has(m[1])) unknown.push(`${relative(SRC, file)}: api.${m[1]}`);
      }
    }
    expect(unknown, "api members that do not exist").toEqual([]);
  });

  it("talks to the backend only through api.js", () => {
    const offenders = [];
    for (const file of walk(SRC)) {
      if (file === API_FILE) continue;
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(/fetch\(([^)]*)\)/g)) {
        // Settings.jsx asks api.github.com for the latest release; that is not the backend.
        if (/BASE|["'`]\/(api|rpc|sse)/.test(m[1])) offenders.push(`${relative(SRC, file)}: fetch(${m[1].trim()})`);
      }
    }
    expect(offenders, "backend requests outside api.js").toEqual([]);
  });

  it("prints the routes nothing in the frontend uses (information, not a failure)", () => {
    const used = new Set(requests.map(({ method, path }) => `${method} ${path}`));
    const unused = MANIFEST.filter((entry) => !used.has(entry) && !/^(GET \/(docs|redoc|openapi\.json|health|sse)|MOUNT )/.test(entry) && !/\{/.test(entry));
    if (unused.length) console.log("manifest routes no frontend code requests:\n  " + unused.join("\n  "));
  });
});
