"""An imported or restored database is upgraded to OpenFlow's schema on the spot.

Seen 2026-09-11: another owner's beta-era NayaFlow user-data.db imported cleanly ("ok",
1 profile) and then every page answered 500 "no such column: animation_id" / "variant",
because the additive migrations only ran at startup. No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import backup as bak            # noqa: E402
from openflow_backend.db import database as dbm          # noqa: E402


def _beta_db(path: Path) -> bytes:
    """The shape of the beta database: the tables exist, the later columns do not."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, order_id INT, state TEXT, icon_id TEXT, author_name TEXT,
                               description TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, icon_id TEXT, profile_id TEXT, author_name TEXT,
                             description TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_configs (name TEXT, order_id INT, icon_id TEXT, author_name TEXT,
                                     description TEXT, size INT, type TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE settings (value TEXT, correlation_id TEXT, type TEXT, created_at TEXT, updated_at TEXT);
        INSERT INTO profiles VALUES ('Beta', 0, 'ON_BOARD', NULL, NULL, NULL, 'p1', '', '');
        INSERT INTO layers VALUES ('QWERTY', 0, NULL, 'p1', NULL, NULL, 'l1', '', '');
        INSERT INTO module_configs VALUES ('Naya Track', 0, NULL, NULL, NULL, 0, 'TRACK', 'm1', '', '');
    """)
    conn.commit(); conn.close()
    return path.read_bytes()


def _columns(path: Path, table: str) -> set:
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_an_imported_beta_database_gets_the_missing_columns_at_once(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    (data / "backups").mkdir()
    live = data / "user-data.db"
    monkeypatch.setattr(bak, "db_path", lambda: live)
    monkeypatch.setattr(bak, "backups_dir", lambda: data / "backups")
    monkeypatch.setattr(dbm, "db_path", lambda: live, raising=False)
    monkeypatch.setattr(dbm, "connect", lambda path=None: _row_conn(live))
    # a current database is in place first, so there is something to back up
    dbm.init_db(live)
    raw = _beta_db(tmp_path / "beta.db")
    out = bak.import_db_bytes(raw, "user-data-beta.db")
    assert out == {"ok": True, "profiles": 1}
    assert "animation_id" in _columns(live, "layers"), "the page that failed with 500"
    assert {"module_led_left", "module_led_right"} <= _columns(live, "layers")
    assert {"variant", "captured_from"} <= _columns(live, "module_configs")


def _row_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
