// OpenFlow's report relay: an in-app bug report, screenshots included, filed in Jira.
//
// Why a relay. Tester installers file reports through a Jira automation webhook, which is safe to
// ship (it can fire one rule and nothing else) but carries JSON fields only: a rule cannot turn
// uploaded bytes into an attachment. Attaching needs the REST API and an account API token, and
// that token must never be inside an installer (backend/openflow_backend/report.py). So the token
// lives here, as a Worker secret, and installers carry only this Worker's URL. The worst an
// extracted URL buys anyone is reports in the inbox queue, which is what the webhook risked too.
//
//   POST /report   {"summary", "description", "contact"?, "page"?, "source"?,
//                   "attachments"?: [{"name", "type", "data": <base64>}]}
//   -> 200 {"ok": true, "key": "SCRUM-123", "attached": 2, "failed": []}
//
// Configuration (wrangler.toml [vars]): JIRA_URL, JIRA_PROJECT, JIRA_PARENT, JIRA_ISSUE_TYPE_ID,
// JIRA_LABELS (comma separated), JIRA_SPRINT, JIRA_SPRINT_FIELD.
// Secrets (`npx wrangler secret put ...`): JIRA_EMAIL, JIRA_TOKEN.

const MAX_FILES = 5;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
// Base64 is 4/3 of the bytes; the text and the JSON around it are small next to that.
const MAX_BODY_BYTES = Math.ceil(MAX_FILES * MAX_FILE_BYTES * 4 / 3) + 512 * 1024;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
// Jira Cloud's description field holds 32767 characters.
const MAX_DESCRIPTION = 32000;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

class Refused extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

function decodeAttachments(list) {
  if (list == null) return [];
  if (!Array.isArray(list)) throw new Refused("attachments must be a list");
  if (list.length > MAX_FILES) throw new Refused(`at most ${MAX_FILES} attachments`);
  return list.map((a, i) => {
    const type = String(a?.type || "").toLowerCase();
    if (!IMAGE_TYPES.has(type)) throw new Refused(`attachment ${i + 1} is not a PNG, JPEG, WebP or GIF image`);
    let bytes;
    try {
      const bin = atob(String(a?.data || ""));
      bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    } catch {
      throw new Refused(`attachment ${i + 1} is not valid base64`);
    }
    if (!bytes.length) throw new Refused(`attachment ${i + 1} is empty`);
    if (bytes.length > MAX_FILE_BYTES) throw new Refused(`attachment ${i + 1} is over 5 MB`);
    // A name Jira will show as-is: no path, nothing odd, an extension that matches the type.
    const ext = type.split("/")[1].replace("jpeg", "jpg");
    const base = String(a?.name || `screenshot-${i + 1}`).split(/[\\/]/).pop()
      .replace(/[^\w.\- ]+/g, "_").replace(/\.[^.]*$/, "").slice(0, 80) || `screenshot-${i + 1}`;
    return { name: `${base}.${ext}`, type, bytes };
  });
}

function jiraAuth(env) {
  return "Basic " + btoa(`${env.JIRA_EMAIL}:${env.JIRA_TOKEN}`);
}

async function createIssue(env, summary, description) {
  const fields = {
    project: { key: env.JIRA_PROJECT },
    summary,
    description,
    issuetype: { id: String(env.JIRA_ISSUE_TYPE_ID) },
    labels: String(env.JIRA_LABELS || "").split(",").map((s) => s.trim()).filter(Boolean),
  };
  if (env.JIRA_PARENT) fields.parent = { key: env.JIRA_PARENT };
  const post = (f) => fetch(`${env.JIRA_URL.replace(/\/+$/, "")}/rest/api/2/issue`, {
    method: "POST",
    headers: { authorization: jiraAuth(env), "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ fields: f }),
  });
  // The inbox sprint is best effort, as in report.py: a site that refuses the sprint field on
  // create still gets the report, filed outside the sprint.
  if (env.JIRA_SPRINT && env.JIRA_SPRINT_FIELD) {
    const r = await post({ ...fields, [env.JIRA_SPRINT_FIELD]: Number(env.JIRA_SPRINT) });
    if (r.ok) return (await r.json()).key;
    if (r.status !== 400 && r.status !== 403) {
      throw new Refused(`Jira refused the report (${r.status}): ${(await r.text()).slice(0, 300)}`, 502);
    }
  }
  const r = await post(fields);
  if (!r.ok) throw new Refused(`Jira refused the report (${r.status}): ${(await r.text()).slice(0, 300)}`, 502);
  return (await r.json()).key;
}

async function attach(env, key, file) {
  const form = new FormData();
  form.append("file", new Blob([file.bytes], { type: file.type }), file.name);
  const r = await fetch(`${env.JIRA_URL.replace(/\/+$/, "")}/rest/api/2/issue/${key}/attachments`, {
    method: "POST",
    // Jira refuses attachment uploads without this header (its XSRF check).
    headers: { authorization: jiraAuth(env), "x-atlassian-token": "no-check" },
    body: form,
  });
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname !== "/report") return json({ ok: false, error: "not found" }, 404);
    if (request.method !== "POST") return json({ ok: false, error: "POST a report" }, 405);
    if (!env.JIRA_EMAIL || !env.JIRA_TOKEN || !env.JIRA_URL || !env.JIRA_PROJECT) {
      return json({ ok: false, error: "the relay is not configured" }, 503);
    }
    if (Number(request.headers.get("content-length") || 0) > MAX_BODY_BYTES) {
      return json({ ok: false, error: "the report is too large" }, 413);
    }
    try {
      let body;
      try { body = await request.json(); } catch { throw new Refused("the report is not JSON"); }
      const summary = String(body?.summary || "").replace(/\s+/g, " ").trim().slice(0, 250);
      let description = String(body?.description || "");
      if (!summary || !description.trim()) throw new Refused("a report needs a summary and a description");
      if (description.length > MAX_DESCRIPTION) {
        description = description.slice(0, MAX_DESCRIPTION) + "\n\n(truncated by the relay)";
      }
      const files = decodeAttachments(body.attachments);

      const key = await createIssue(env, summary, description);
      // The issue exists now; an attachment that fails is reported, not fatal, so the user is
      // never told "not filed" about a report that was.
      const failed = [];
      for (const f of files) {
        try { await attach(env, key, f); } catch (e) { failed.push({ name: f.name, reason: e.message }); }
      }
      return json({ ok: true, key, attached: files.length - failed.length, failed });
    } catch (e) {
      return json({ ok: false, error: e.message }, e instanceof Refused ? e.status : 500);
    }
  },
};
