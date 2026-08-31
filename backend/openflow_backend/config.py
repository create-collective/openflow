"""Runtime configuration.

Mirrors how NayaFlow located its user data, but under an OpenFlow-owned path so
the two apps never share a database.
"""

from __future__ import annotations

import os
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
