"""Runtime configuration.

Mirrors how NayaFlow located its user data, but under an OpenFlow-owned path so
the two apps never share a database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """Per-user application data directory (created on first use)."""
    override = os.environ.get("OPENFLOW_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "OpenFlow"
    elif os.sys.platform == "darwin":  # type: ignore[attr-defined]
        base = Path.home() / "Library" / "Application Support" / "OpenFlow"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "OpenFlow"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "user-data.db"


def backups_dir() -> Path:
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Default port. The Electron shell passes the real one on argv (as NayaFlow did),
# and the renderer falls back to 3001 — so we keep 3001 as the standalone default.
DEFAULT_PORT = int(os.environ.get("OPENFLOW_BACKEND_PORT", "3001"))


def instance_token() -> str | None:
    """The per-launch token the desktop shell hands us (OPENFLOW_INSTANCE). It is echoed by
    /api/info/system so the shell can tell its own sidecar from any other server on the port,
    and required by /rpc/shutdown so nothing else can stop us."""
    return os.environ.get("OPENFLOW_INSTANCE") or None


# --- Bundled resources -------------------------------------------------------------------
#
# Running from source, the reference data (docs/reference), the first-run database snapshot
# (device/userdata-snapshot) and the built renderer (frontend/dist) are found by walking up from
# this file, which works whether openflow/ is nested in the NayaOS monorepo or is a repository
# of its own. Frozen with PyInstaller (the desktop sidecar), the same files are collected under
# <_MEIPASS>/resources by openflow_backend.spec. Everything that needs one of them asks here, so
# exactly one place knows where they are; callers treat None as "not available".


def is_frozen() -> bool:
    """True inside a PyInstaller build."""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def resources_dir() -> Path | None:
    """The bundled read-only resources directory, or None when running from source.

    OPENFLOW_RESOURCES_DIR overrides it (the sidecar smoke test, or a source checkout pointed at
    a built bundle)."""
    override = os.environ.get("OPENFLOW_RESOURCES_DIR")
    if override:
        return Path(override)
    if is_frozen():
        return Path(sys._MEIPASS) / "resources"  # type: ignore[attr-defined]
    return None


def _walk_up_for(*rel: str) -> Path | None:
    """The first ancestor of this file that contains rel: the source checkout layout."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent.joinpath(*rel)
        if candidate.exists():
            return candidate
    return None


def reference_dir() -> Path | None:
    """docs/reference: app-shortcuts.json, shortcut-dictionary.json, firmware-catalog.json, and
    ATTRIBUTION.md, which must travel with them."""
    r = resources_dir()
    return r / "reference" if r else _walk_up_for("docs", "reference")


def renderer_dir() -> Path | None:
    """The built renderer (frontend/dist) served at /, when there is one."""
    r = resources_dir()
    return r / "renderer" if r else _walk_up_for("frontend", "dist")


def seed_db_path() -> Path | None:
    """The database a first run starts from: NayaFlow's stock profiles and module configs, no
    device identity (device/userdata-snapshot/user-data-2026-08-28.db in the checkout)."""
    r = resources_dir()
    if r:
        found = sorted((r / "seed").glob("*.db"))
        return found[0] if found else None
    return _walk_up_for("device", "userdata-snapshot", "user-data-2026-08-28.db")
