# -*- mode: python ; coding: utf-8 -*-
#
# The OpenFlow backend as a desktop sidecar: one directory, one process, started by the Electron
# shell with a port on argv (see electron/main.js) and stopped through /rpc/shutdown.
#
#     cd backend && python -m PyInstaller openflow_backend.spec --noconfirm
#     -> dist/openflow-backend/openflow-backend[.exe]
#
# onedir, not onefile: onefile's bootloader is a second process that unpacks ~40 MB into %TEMP%
# on every launch and, when killed, orphans the real server holding the keyboard's serial port.
# console=True: a --noconsole build leaves sys.stdout as None and uvicorn's logging falls over;
# the shell spawns us with windowsHide so no window appears. upx=False: compressed executables
# are what antivirus heuristics flag.
#
# Everything the backend reads at runtime travels under _internal/resources and is found through
# openflow_backend.config (resources_dir() when frozen), never by walking up from a source file:
#   resources/reference/   docs/reference: app-shortcuts.json, shortcut-dictionary.json,
#                          firmware-catalog.json, ATTRIBUTION.md (ShortcutMapper, MIT)
#   resources/seed/        the first-run database snapshot
#   resources/renderer/    frontend/dist, served at /
#   resources/LICENSE      Apache-2.0
# The package's own data (db/schema.sql, db/*.json, device/*.json, the vendored nayactl LICENSE)
# is collected next to the package by collect_data_files.
import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

BACKEND = Path(SPECPATH)                # noqa: F821  (PyInstaller injects SPECPATH)
OPENFLOW = BACKEND.parent


def _walk_up(*rel):
    """First directory at or above openflow/ containing rel: the monorepo keeps docs/reference
    and device/userdata-snapshot two levels above openflow/, a standalone checkout at its root."""
    for base in [OPENFLOW, *OPENFLOW.parents]:
        cand = base.joinpath(*rel)
        if cand.exists():
            return cand
    raise SystemExit(f"openflow_backend.spec: not found at or above {OPENFLOW}: {'/'.join(rel)} "
                     "(set OPENFLOW_REFERENCE_DIR / OPENFLOW_SEED_DB to point at them)")


REFERENCE = Path(os.environ.get("OPENFLOW_REFERENCE_DIR") or _walk_up("docs", "reference"))
SEED_DB = Path(os.environ.get("OPENFLOW_SEED_DB") or _walk_up("device", "userdata-snapshot", "user-data-2026-08-28.db"))
RENDERER = OPENFLOW / "frontend" / "dist"
if not (RENDERER / "index.html").is_file():
    raise SystemExit("openflow_backend.spec: frontend/dist/index.html is missing; run `npm run build:frontend` first")
for name in ("app-shortcuts.json", "shortcut-dictionary.json", "firmware-catalog.json", "ATTRIBUTION.md"):
    if not (REFERENCE / name).is_file():
        raise SystemExit(f"openflow_backend.spec: {REFERENCE / name} is missing")

datas = collect_data_files("openflow_backend")          # schema.sql, *.json, _vendor LICENSE, VENDOR.md
datas += [(str(REFERENCE / name), "resources/reference") for name in
          ("app-shortcuts.json", "shortcut-dictionary.json", "firmware-catalog.json", "ATTRIBUTION.md")]
datas += [
    (str(SEED_DB), "resources/seed"),
    (str(RENDERER), "resources/renderer"),
    (str(OPENFLOW / "LICENSE"), "resources"),
]

# Where in-app reports go, baked in so an installed copy can file one with no setup. Only ever
# an automation WEBHOOK url: the secret in it fires one rule that creates one issue, it cannot
# read or edit anything, and regenerating the rule's webhook rotates it. An account API token is
# scoped to the whole ACCOUNT and must never be built in.
#
# The value comes from OPENFLOW_REPORT_WEBHOOK, or from backend/report-sink.json (gitignored) if
# that exists. Neither is in the repository, so the URL never enters git history. A build with
# neither still succeeds -- the app then offers the report to be copied or saved.
#
# The report RELAY (relay/report-relay/, OPENFLOW_REPORT_RELAY) is baked the same way and is
# preferred when present: a Cloudflare Worker that holds the Jira token itself and is the one
# sink that carries screenshots. Its URL, like the webhook's, can only file reports.
_sink_src = BACKEND / "report-sink.json"
_sink_file = json.loads(_sink_src.read_text(encoding="utf-8")) if _sink_src.is_file() else {}
_sinks = {
    "webhook": (os.environ.get("OPENFLOW_REPORT_WEBHOOK", "").strip()
                or str(_sink_file.get("webhook") or "").strip()),
    "relay": (os.environ.get("OPENFLOW_REPORT_RELAY", "").strip()
              or str(_sink_file.get("relay") or "").strip()),
}
_sinks = {k: v for k, v in _sinks.items() if v}
if _sinks:
    for _k, _v in _sinks.items():
        if not _v.startswith("https://"):
            raise SystemExit(f"openflow_backend.spec: the report {_k} must be an https url")
    _sink_out = BACKEND / "build" / "report-sink.json"
    _sink_out.parent.mkdir(parents=True, exist_ok=True)
    _sink_out.write_text(json.dumps(_sinks), encoding="utf-8")
    datas += [(str(_sink_out), "resources")]
    for _k, _v in _sinks.items():
        print(f"openflow_backend.spec: in-app reports: {_k} at {_v.split('/')[2]}")
else:
    print("openflow_backend.spec: no report sink configured; reports will be copy/save only")

hiddenimports = (
    collect_submodules("uvicorn")                        # lifespan/loop/http classes are resolved by name
    + collect_submodules("openflow_backend._vendor.nayactl")   # the vendored protocol layer
    + ["python_multipart", "multipart",                  # FastAPI probes these at route-definition time
       "sse_starlette", "sse_starlette.sse",
       "serial.tools.list_ports", "serial.tools.list_ports_common"]
)
if sys.platform == "win32":
    hiddenimports += ["serial.win32", "serial.serialwin32", "serial.tools.list_ports_windows"]
else:
    hiddenimports += ["serial.serialposix", "serial.tools.list_ports_posix",
                      "serial.tools.list_ports_osx", "serial.tools.list_ports_linux"]

a = Analysis(
    [str(BACKEND / "sidecar_main.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # __main__ pins loop="asyncio", http="h11", ws="none", so none of these are ever imported.
    excludes=["uvloop", "watchfiles", "websockets", "wsproto", "httptools",
              "tkinter", "pytest", "_pytest", "httpx", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openflow-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="openflow-backend",
)
