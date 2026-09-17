"""The in-app bug report: what gets collected, what gets stripped, and where it is sent.

The report is assembled here rather than in the browser so it can carry things the renderer
cannot see (the backend version, the Python it runs on, the device log) and so the SINK is a
backend concern. Today there is one sink, Jira, and it is off unless credentials are configured
on this machine.

**No secret ships with OpenFlow.** The Jira site, project, parent epic and sprint are not
secrets and have defaults below; the account email and API token are read from the environment
or from `<data dir>/jira.json`, neither of which is in the repository or the installer. A build
with no credentials returns `configured: false` and the app falls back to letting the user copy
or save the report themselves. That is deliberate: an API token is scoped to an ACCOUNT, not to
a project, so a token inside a distributed binary would hand every reader the owner's Jira.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .config import data_dir

# Not secrets: the site and the queue are already written down in the project's own docs.
JIRA_DEFAULTS = {
    "url": "https://traviswye.atlassian.net",
    "project": "SCRUM",
    "parent": "SCRUM-79",          # epic: User-submitted bugs and issues
    "sprint": 9,                   # "Inbox: user reports", kept future so it stays a queue
    "sprintField": "customfield_10020",
    "issueTypeId": "10003",        # Task (this project has no Bug type)
    "labels": ["user-reported", "needs-triage"],
}
JIRA_FILE = "jira.json"
_TIMEOUT_S = 20

# Key names whose VALUES identify a particular unit or person. Matched case-insensitively as
# substrings, so a new field named "leftBleAddress" is covered without another edit here.
_IDENTIFYING = ("address", "hardwareid", "serial", "uuid", "instance")


def _is_identifying(key: str) -> bool:
    k = key.lower().replace("_", "")
    return any(frag in k for frag in _IDENTIFYING)


def redact(value: Any) -> Any:
    """Replace identifying values with a marker, everywhere in a nested structure."""
    if isinstance(value, dict):
        return {k: ("(removed)" if _is_identifying(k) and v not in (None, "", [])
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def collect_context(svc, log_entries: list[dict] | None = None, last_status: dict | None = None) -> dict:
    """Everything about this machine and keyboard worth having on a report.

    Reads nothing from the device: a report is often filed BECAUSE the device is misbehaving,
    and a blocking read would be the last thing to do at that moment. The halves come from the
    backend's record of the last read, which is what the app itself is showing.
    """
    try:
        devices = svc.list_devices()
    except Exception as e:                                  # never let the report fail on this
        devices = [{"error": str(e)}]
    return {
        "app": {
            "version": __version__,
            "os": platform.platform(),
            "arch": platform.machine(),
            "python": platform.python_version(),
            "frozen": bool(getattr(__import__("sys"), "frozen", False)),
        },
        "usbDevices": devices,
        "lastStatus": last_status or {},
        "deviceLog": (log_entries or [])[-40:],
    }


def render(form: dict, context: dict) -> str:
    """The report as text. Jira Cloud's v2 API takes a plain string, so this is what is filed
    and also what the user copies when there is no sink."""
    when = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    app = context.get("app", {})
    out = [
        f"*Reported from OpenFlow {app.get('version', '?')}*  ·  {when}",
        "",
        "h3. What happened",
        (form.get("happened") or "(not given)").strip(),
        "",
        "h3. What was expected",
        (form.get("expected") or "(not given)").strip(),
        "",
        "h3. Steps to reproduce",
        (form.get("steps") or "(not given)").strip(),
        "",
        "h3. Environment",
        f"* OpenFlow {app.get('version', '?')} ({'packaged' if app.get('frozen') else 'dev build'})",
        f"* {app.get('os', '?')} · {app.get('arch', '?')} · Python {app.get('python', '?')}",
        f"* Page: {form.get('page') or '(unknown)'}",
    ]
    halves = (context.get("lastStatus") or {}).get("halves") or []
    for h in halves:
        mod = h.get("module") or {}
        bits = [
            f"{h.get('description') or h.get('side') or 'half'}:",
            "connected" if h.get("connected") else "not connected",
        ]
        if h.get("firmwareVersion"):
            bits.append(f"fw {h['firmwareVersion']}")
        if h.get("port"):
            bits.append(str(h["port"]))
        if mod.get("type"):
            bits.append(f"module {mod['type']}"
                        + (f" fw {mod['firmwareVersion']}" if mod.get("firmwareVersion") else ""))
        out.append("* " + " · ".join(bits))
    if form.get("contact"):
        out += ["", "h3. Contact", form["contact"].strip()]
    log = context.get("deviceLog") or []
    if log:
        out += ["", "h3. Recent device I/O", "{code}"]
        for e in log:
            out.append(f"{e.get('at', '')} {e.get('kind', '')} {e.get('port', '')} "
                       f"{e.get('detail', '')} {'' if e.get('ok', True) else 'FAILED'}".rstrip())
        out.append("{code}")
    out += ["", "h3. Collected data", "{code:json}",
            json.dumps({k: v for k, v in context.items() if k != "deviceLog"}, indent=1),
            "{code}"]
    return "\n".join(out)


# --- the Jira sink ---------------------------------------------------------------------- #

def jira_config() -> dict | None:
    """Defaults, overlaid with `<data dir>/jira.json`, overlaid with the environment. Returns
    None unless an account email and API token are present, since nothing can be filed without
    them."""
    cfg = dict(JIRA_DEFAULTS)
    path = data_dir() / JIRA_FILE
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
    except Exception:
        pass                                      # a malformed file must not break the page
    for key, env in (("url", "OPENFLOW_JIRA_URL"), ("project", "OPENFLOW_JIRA_PROJECT"),
                     ("parent", "OPENFLOW_JIRA_PARENT"), ("email", "OPENFLOW_JIRA_EMAIL"),
                     ("token", "OPENFLOW_JIRA_TOKEN"), ("sprint", "OPENFLOW_JIRA_SPRINT")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if not cfg.get("email") or not cfg.get("token"):
        return None
    try:
        cfg["sprint"] = int(cfg["sprint"]) if cfg.get("sprint") not in (None, "") else None
    except (TypeError, ValueError):
        cfg["sprint"] = None
    return cfg


def _jira_post(cfg: dict, fields: dict) -> dict:
    body = json.dumps({"fields": fields}).encode("utf-8")
    auth = base64.b64encode(f"{cfg['email']}:{cfg['token']}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/rest/api/2/issue",
        data=body, method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def submit_to_jira(cfg: dict, summary: str, description: str) -> dict:
    """Create the issue. The sprint is best-effort: a site that will not take the sprint field
    on create must still get the report, so it is retried without it and the caller is told."""
    fields = {
        "project": {"key": cfg["project"]},
        "summary": summary[:250],
        "description": description,
        "issuetype": {"id": str(cfg["issueTypeId"])},
        "labels": list(cfg["labels"]),
    }
    if cfg.get("parent"):
        fields["parent"] = {"key": cfg["parent"]}
    sprint_note = None
    if cfg.get("sprint"):
        try:
            data = _jira_post(cfg, {**fields, cfg["sprintField"]: cfg["sprint"]})
            return {"key": data.get("key"), "sprint": True}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code not in (400, 403):
                raise RuntimeError(f"Jira refused the report ({e.code}): {detail}") from e
            sprint_note = f"filed outside the inbox sprint ({e.code}): {detail}"
    data = _jira_post(cfg, fields)
    return {"key": data.get("key"), "sprint": False, "note": sprint_note}


def file_report(svc, form: dict, context: dict) -> dict:
    """Render the report and file it if a sink is configured. Always returns the rendered text,
    so the page can offer it for copying when there is nowhere to send it."""
    title = (form.get("title") or "").strip() or "OpenFlow report (no title given)"
    summary = re.sub(r"\s+", " ", title)[:250]
    description = render(form, context)
    cfg = jira_config()
    if cfg is None:
        return {"ok": False, "configured": False, "reason": "no-sink",
                "summary": summary, "description": description}
    try:
        res = submit_to_jira(cfg, summary, description)
    except Exception as e:
        return {"ok": False, "configured": True, "reason": str(e),
                "summary": summary, "description": description}
    key = res.get("key")
    return {"ok": True, "configured": True, "sink": "jira", "key": key,
            "url": f"{cfg['url'].rstrip('/')}/browse/{key}" if key else None,
            "sprint": res.get("sprint"), "note": res.get("note"),
            "summary": summary, "description": description}
