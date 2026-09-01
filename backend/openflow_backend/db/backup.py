"""Local backups of the user-data DB (snapshot files), plus a portable
full-data JSON export/import.

Mirrors NayaFlow: automatic + manual local backups you can restore from a list.
Backups are plain SQLite snapshots in the app's backups dir.
"""

from __future__ import annotations

import io
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

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


def open_dir() -> dict:
    """Open the backups folder in the OS file manager (the button NayaFlow lacked)."""
    import os
    import subprocess
    import sys

    d = backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(d))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)])
    return {"ok": True, "dir": str(d)}


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


def import_db_bytes(raw: bytes, filename: str) -> dict:
    """Install an uploaded database as the current data. Accepts a raw .db or a
    NayaFlow backup .zip (which bundles user-data.db) — OpenFlow uses NayaFlow's
    schema, so a NayaFlow backup drops straight in."""
    db_bytes = raw
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith(".db")), None)
            if member is None:
                raise ValueError("zip contains no .db file")
            db_bytes = zf.read(member)

    # Validate it is a SQLite DB with the expected schema.
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        tf.write(db_bytes)
        tmp_path = Path(tf.name)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            has_profiles = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'"
            ).fetchone()
            if not has_profiles:
                raise ValueError("not a NayaFlow/OpenFlow database (no profiles table)")
            n = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        finally:
            conn.close()
    finally:
        tmp_path.unlink(missing_ok=True)

    create_backup(kind="pre-import")
    db_path().write_bytes(db_bytes)
    return {"ok": True, "profiles": n}
