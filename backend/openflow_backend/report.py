"""The in-app bug report: what gets collected, what gets stripped, and where it is sent.

The report is assembled here rather than in the browser so it can carry things the renderer
cannot see (the backend version, the Python it runs on, the device log) and so the SINK is a
backend concern. Both sinks file into Jira, and both are off unless this machine is configured
for one.

**No secret ships with OpenFlow.** The Jira site, project, parent epic and sprint are not
secrets and have defaults below; anything that authenticates is read from the environment or
from `<data dir>/jira.json`, neither of which is in the repository or the installer. A build
with nothing configured returns `configured: false` and the app falls back to letting the user
copy or save the report themselves.

Two sinks, and the safer one wins when both are present:

1. **An automation incoming webhook** (`webhook`). Atlassian generates and hosts the URL; the
   secret in it can do exactly one thing, fire that one rule, which creates the issue with the
   parent, sprint and labels the rule carries. It cannot read anything, edit anything or reach
   another project, and regenerating the webhook rotates it. The worst an extracted URL buys
   anyone is junk in the inbox queue. This is the one to ship to testers.
   It carries text only: an automation rule cannot attach files, so a screenshot cannot
   travel this way.
0. **The report relay** (`relay`), preferred over both: a Cloudflare Worker of the owner's
   (relay/report-relay/) that holds the API token as its own secret, creates the issue and
   attaches the screenshots. An installer carries only its URL, which, like the webhook, can
   do nothing but file a report.
2. **An account API token** (`email` + `token`). Full REST access, so it returns the issue key
   and can set the sprint on create, but it authenticates as the ACCOUNT, not as a project. One
   inside a distributed binary would hand every reader the owner's whole Jira, so it belongs on
   a trusted machine only.
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
from .config import data_dir, resources_dir

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
JIRA_FILE = "jira.json"          # this machine's own config, in the data directory
SINK_FILE = "report-sink.json"   # what the installer shipped, if anything (openflow_backend.spec)
_TIMEOUT_S = 20
# Sent on every request. Cloudflare's bot check refuses Python's default `Python-urllib`
# agent (error 1010) before a request reaches the report relay, which is how the first test
# report from the app was turned away (2026-10-05).
_USER_AGENT = f"OpenFlow/{__version__}"

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

def _overlay(cfg: dict, path: Path | None) -> None:
    """Merge a JSON file over cfg, if it is there and readable. A malformed one is ignored:
    a bad config file must not take the report page down with it."""
    if path is None:
        return
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
    except Exception:
        pass


def jira_config() -> dict | None:
    """Where a report goes, from three places, each overriding the one before:

    1. `resources/report-sink.json`, baked in at build time — this is how a tester's installer
       arrives already able to file, with no setup. Only ever a WEBHOOK: it can do one thing,
       fire one rule, and is rotated by regenerating it. An account token must never go here.
    2. `<data dir>/jira.json`, this machine's own config, so a developer or a tester can point
       reports somewhere else without rebuilding.
    3. `OPENFLOW_JIRA_*` in the environment, which wins over both.

    Returns None when there is nothing to file with, and the app then offers the report to be
    copied or saved instead.
    """
    cfg = dict(JIRA_DEFAULTS)
    res = resources_dir()
    _overlay(cfg, (res / SINK_FILE) if res is not None else None)
    _overlay(cfg, data_dir() / JIRA_FILE)
    for key, env in (("url", "OPENFLOW_JIRA_URL"), ("project", "OPENFLOW_JIRA_PROJECT"),
                     ("parent", "OPENFLOW_JIRA_PARENT"), ("email", "OPENFLOW_JIRA_EMAIL"),
                     ("token", "OPENFLOW_JIRA_TOKEN"), ("sprint", "OPENFLOW_JIRA_SPRINT"),
                     ("webhook", "OPENFLOW_JIRA_WEBHOOK"), ("relay", "OPENFLOW_REPORT_RELAY")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if not cfg.get("relay") and not cfg.get("webhook") and not (cfg.get("email") and cfg.get("token")):
        return None
    try:
        cfg["sprint"] = int(cfg["sprint"]) if cfg.get("sprint") not in (None, "") else None
    except (TypeError, ValueError):
        cfg["sprint"] = None
    return cfg


def sink_kind(cfg: dict | None) -> str | None:
    """Which sink a report would go to, in the order file_report tries them."""
    if cfg is None:
        return None
    return "relay" if cfg.get("relay") else "webhook" if cfg.get("webhook") else "jira"


def carries_attachments(cfg: dict | None) -> bool:
    """The webhook takes text only; the relay and the API token can attach files."""
    return sink_kind(cfg) in ("relay", "jira")


# Screenshots: the same limits the relay enforces (relay/report-relay/src/index.js).
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
ATTACHMENT_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def clean_attachments(raw) -> list[dict]:
    """Validate what the page sent: [{"name", "type", "data": base64}], decoded and checked
    here so a bad file is refused with a reason before anything is filed."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("attachments must be a list")
    if len(raw) > MAX_ATTACHMENTS:
        raise ValueError(f"attach at most {MAX_ATTACHMENTS} screenshots")
    out = []
    for i, a in enumerate(raw, 1):
        a = a if isinstance(a, dict) else {}
        kind = str(a.get("type") or "").lower()
        if kind not in ATTACHMENT_TYPES:
            raise ValueError(f"attachment {i} is not a PNG, JPEG, WebP or GIF image")
        try:
            data = base64.b64decode(str(a.get("data") or ""), validate=True)
        except Exception:
            raise ValueError(f"attachment {i} could not be read") from None
        if not data:
            raise ValueError(f"attachment {i} is empty")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"attachment {i} is over 5 MB")
        base = str(a.get("name") or f"screenshot-{i}").replace("\\", "/").split("/")[-1]
        name = re.sub(r"[^\w.\- ]+", "_", base)[:100] or f"screenshot-{i}"
        out.append({"name": name, "type": kind, "bytes": data})
    return out


def submit_to_relay(url: str, summary: str, description: str, form: dict,
                    attachments: list[dict]) -> dict:
    """POST the report and its screenshots to the relay, which files and attaches them."""
    body = json.dumps({
        "summary": summary,
        "description": description,
        "contact": (form.get("contact") or "").strip(),
        "page": form.get("page") or "",
        "source": "openflow-app",
        "attachments": [{"name": a["name"], "type": a["type"],
                         "data": base64.b64encode(a["bytes"]).decode("ascii")} for a in attachments],
    }).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + "/report", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            reason = None
        raise RuntimeError(reason or f"the report relay answered {e.code}") from e
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "the report relay did not file the report")
    return data


def submit_to_webhook(url: str, summary: str, description: str, form: dict) -> dict:
    """POST the report at an automation incoming webhook. The rule decides what to create, so
    nothing here names a project, a parent or a sprint; the fields below are what the rule reads
    as `{{webhookData.summary}}` and so on. Automation answers before the rule has run, so there
    is no issue key to hand back -- the app says "sent", not "sent as SCRUM-123"."""
    body = json.dumps({
        "summary": summary,
        "description": description,
        "contact": (form.get("contact") or "").strip(),
        "page": form.get("page") or "",
        "source": "openflow-app",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        return {"status": r.status}


def _jira_post(cfg: dict, fields: dict) -> dict:
    body = json.dumps({"fields": fields}).encode("utf-8")
    auth = base64.b64encode(f"{cfg['email']}:{cfg['token']}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/rest/api/2/issue",
        data=body, method="POST",
        headers={"User-Agent": _USER_AGENT, "Authorization": f"Basic {auth}", "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def _jira_attach(cfg: dict, key: str, attachment: dict) -> None:
    """One file onto an issue: multipart, with the header Jira's XSRF check wants."""
    boundary = "openflow" + os.urandom(12).hex()
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{attachment['name']}\"\r\nContent-Type: {attachment['type']}\r\n\r\n")
    body = head.encode("utf-8") + attachment["bytes"] + f"\r\n--{boundary}--\r\n".encode("ascii")
    auth = base64.b64encode(f"{cfg['email']}:{cfg['token']}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + f"/rest/api/2/issue/{key}/attachments", data=body, method="POST",
        headers={"User-Agent": _USER_AGENT, "Authorization": f"Basic {auth}", "X-Atlassian-Token": "no-check",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S):
        pass


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
    try:
        attachments = clean_attachments(form.get("attachments"))
    except ValueError as e:
        # Refused before anything is filed, so the user can fix the file and send once.
        return {"ok": False, "configured": jira_config() is not None, "reason": str(e),
                "summary": title, "description": ""}
    summary = re.sub(r"\s+", " ", title)[:250]
    description = render(form, context)
    cfg = jira_config()
    if cfg is None:
        return {"ok": False, "configured": False, "reason": "no-sink",
                "summary": summary, "description": description}
    # The relay first: it can only file reports, and it is the one that carries screenshots.
    if cfg.get("relay"):
        try:
            res = submit_to_relay(cfg["relay"], summary, description, form, attachments)
        except Exception as e:
            return {"ok": False, "configured": True, "reason": str(e),
                    "summary": summary, "description": description}
        return {"ok": True, "configured": True, "sink": "relay", "key": res.get("key"), "url": None,
                "attached": res.get("attached", 0), "attachFailed": res.get("failed") or [],
                "summary": summary, "description": description}
    # The webhook next when both are configured: it can only create, so a machine that has one
    # never needs to reach for the account token. It carries text only.
    if cfg.get("webhook"):
        try:
            submit_to_webhook(cfg["webhook"], summary, description, form)
        except Exception as e:
            return {"ok": False, "configured": True, "reason": str(e),
                    "summary": summary, "description": description}
        return {"ok": True, "configured": True, "sink": "webhook", "key": None, "url": None,
                "attached": 0, "attachSkipped": len(attachments),
                "summary": summary, "description": description}
    try:
        res = submit_to_jira(cfg, summary, description)
    except Exception as e:
        return {"ok": False, "configured": True, "reason": str(e),
                "summary": summary, "description": description}
    key = res.get("key")
    failed = []
    for a in attachments if key else []:
        try:
            _jira_attach(cfg, key, a)
        except Exception as e:
            failed.append({"name": a["name"], "reason": str(e)})
    return {"ok": True, "configured": True, "sink": "jira", "key": key,
            "attached": (len(attachments) - len(failed)) if key else 0, "attachFailed": failed,
            "url": f"{cfg['url'].rstrip('/')}/browse/{key}" if key else None,
            "sprint": res.get("sprint"), "note": res.get("note"),
            "summary": summary, "description": description}
