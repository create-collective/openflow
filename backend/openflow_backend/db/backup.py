"""Local backups of the user-data DB (snapshot files), plus a portable
full-data JSON export/import.

Mirrors NayaFlow: automatic + manual local backups you can restore from a list.
Backups are plain SQLite snapshots in the app's backups dir.
"""

from __future__ import annotations

import shutil
from datetime import datetime

from ..config import backups_dir, db_path

MAX_AUTO_BACKUPS = 20


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def create_backup(kind: str = "manual") -> dict:
    src = db_path()
    if not src.exists():
        raise ValueError("no database to back up")
    name = f"openflow-{kind}-{_stamp()}.db"
    dest = backups_dir() / name
    shutil.copyfile(src, dest)
    if kind == "auto":
        _prune_auto()
    return {"ok": True, "name": name}


def _prune_auto():
    autos = sorted(backups_dir().glob("openflow-auto-*.db"), key=lambda p: p.stat().st_mtime)
    for old in autos[:-MAX_AUTO_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups() -> dict:
    out = []
    for p in sorted(backups_dir().glob("openflow-*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({
            "name": p.name,
            "path": str(p),
            "sizeKb": round(st.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "kind": "auto" if "-auto-" in p.name else "manual",
        })
    return {"backups": out, "dir": str(backups_dir())}


def restore_backup(name: str) -> dict:
    # Only allow names within the backups dir (no path traversal).
    src = backups_dir() / name
    if not src.exists() or src.parent != backups_dir():
        raise ValueError(f"backup not found: {name}")
    # Snapshot current state first, then restore.
    create_backup(kind="pre-restore")
    shutil.copyfile(src, db_path())
    return {"ok": True}
