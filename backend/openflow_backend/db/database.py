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


# Columns OpenFlow adds on top of the recovered NayaFlow schema. Additive only: a column
# NayaFlow does not know about is harmless to it, and this keeps existing databases working
# without a rebuild.
_ADDED_COLUMNS = [
    # Which stock variant a module profile was created from. Needed because Track ships two
    # asymmetric variants (left/right) that must group separately in the UI, and the name
    # cannot be trusted for that -- profiles are renameable.
    ("module_configs", "variant", "TEXT"),
    # The device identity a captured profile was taken from. A capture gets its own uuid so it
    # does not seize the row the user has been editing, but it still IS the config sitting in
    # that device slot -- without this the flash cannot tell, allocates a fresh slot, and
    # strands the original on every read->capture->flash cycle.
    ("module_configs", "captured_from", "TEXT"),
    # Per-layer colour for each docked module's LED block. The board has 136 LEDs per layer while
    # the app models 97 key positions, and the blocks past the keys are what light the modules:
    # 88-96 (9) is the LEFT module and 112-126 (15) the RIGHT, measured by painting each band a
    # distinct colour and looking. The left block happens to fall inside the key range so it was
    # already reachable; the right has NO key position at all, which is why a flash left the
    # right module on whatever the last application wrote.
    ("layers", "module_led_left", "TEXT"),
    ("layers", "module_led_right", "TEXT"),
]


# Tables OpenFlow adds that NayaFlow's recovered schema has no equivalent for. Created on every
# open, not just a fresh install, so an existing database picks them up -- schema.sql only runs
# when the DB is empty.
_ADDED_TABLES = [
    # Launch/run steps. NayaFlow's schema has five step tables (standard, text, wait, mouse,
    # loop) and none of them can hold "start this program", so this is ours.
    #
    # `shell` is the whole safety story, and it mirrors Create Companion's split between
    # Action::Launch { program, args } and Action::Command { command }: a launch is argv with no
    # shell involved, so a program name containing metacharacters cannot become a second
    # command. Only a step the user explicitly created as a shell command sets shell=1.
    ("launch_action_macro_steps", """
        CREATE TABLE launch_action_macro_steps (
          id TEXT PRIMARY KEY,
          updated_at TEXT, created_at TEXT,
          order_id INTEGER, delay INTEGER,
          macro_id TEXT,
          program TEXT,        -- the executable, or the full command line when shell=1
          args TEXT,           -- JSON array; empty when shell=1
          shell INTEGER DEFAULT 0
        )"""),
]


def _apply_schema_columns(conn) -> None:
    """Any plain column OpenFlow's BASE schema has that this database lacks.

    An older NayaFlow database is missing whatever NayaFlow added after it was made: a beta-era
    user-data.db imported 2026-09-11 had no `layers.animation_id`, and every page answered "no
    such column" until it was added. The OpenFlow-added columns below never covered those,
    because they only list what OpenFlow itself bolted on. ALTER TABLE can add plain columns
    only, so a PRIMARY KEY or a NOT NULL column without a default is left alone (none of the
    base schema's later columns are either)."""
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(_schema_sql())
        for (name,) in ref.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            present = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if present is None:
                continue
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({name})")}
            for _cid, cname, ctype, notnull, dflt, pk in ref.execute(f"PRAGMA table_info({name})"):
                if cname in have or pk or (notnull and dflt is None):
                    continue
                decl = (ctype or "TEXT") + (f" DEFAULT {dflt}" if dflt is not None else "")
                conn.execute(f"ALTER TABLE {name} ADD COLUMN {cname} {decl}")
    finally:
        ref.close()


def _apply_added_columns(conn) -> None:
    _apply_schema_columns(conn)
    for table, column, decl in _ADDED_COLUMNS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    for name, ddl in _ADDED_TABLES:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if exists is None:
            conn.executescript(ddl)


def init_db(path: Path | None = None) -> None:
    """Create the schema if the database is empty, then apply any additive columns."""
    conn = connect(path)
    try:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'"
        ).fetchone()
        if existing is None:
            conn.executescript(_schema_sql())
        _apply_added_columns(conn)
        # Tag rows that predate the column so new profiles can be grouped beside them.
        from .module_profiles import backfill_variants
        backfill_variants(conn)
        # Device settings used to be stored under their plain id, where the flash path -- which
        # looks them up by NayaFlow's correlation UUID -- could never find them. Carry those
        # rows over so a user's existing choices start taking effect instead of being dropped.
        from .settings import migrate_legacy_setting_keys
        migrate_legacy_setting_keys(conn)
        conn.commit()
    finally:
        conn.close()
