"""SQLite user-data store.

Uses the schema recovered from NayaFlow 1.25.1 (docs/schema.sql), so profiles,
layers, keys, key_bindings, macros, module configs, palettes and templates all
carry the same shape the original app used. This keeps the door open to importing
an existing NayaFlow user-data.db later, and matches the field names the recovered
renderer expects.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from ..config import db_path


def _schema_sql() -> str:
    raw = resources.files("openflow_backend.db").joinpath("schema.sql").read_text(encoding="utf-8")
    # sqlite_sequence is created and managed by SQLite itself; the recovered
    # schema lists it for completeness but it cannot be created manually.
    return "\n".join(
        line for line in raw.splitlines()
        if "CREATE TABLE sqlite_sequence" not in line
    )


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | None = None) -> None:
    """Create the schema if the database is empty."""
    conn = connect(path)
    try:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'"
        ).fetchone()
        if existing is None:
            conn.executescript(_schema_sql())
            conn.commit()
    finally:
        conn.close()
