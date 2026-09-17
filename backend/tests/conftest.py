"""Test session setup: an isolated, initialised data directory.

Tests that do not set OPENFLOW_DATA_DIR themselves read and write the default database through
connect(). On a developer's machine that is %APPDATA%/OpenFlow/user-data.db, which happens to
exist and carry the schema; on a fresh CI runner it is nothing, and every such test failed with
"no such table: settings" (2026-09-16, the project's first CI run). So the session runs against
a temporary data dir with the schema applied, and the developer's real database is never
touched by the suite. A test that sets OPENFLOW_DATA_DIR itself (monkeypatch.setenv) still wins,
because the fixture only fills the variable in when it is unset.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))


@pytest.fixture(scope="session", autouse=True)
def _isolated_initialised_data_dir(tmp_path_factory):
    if os.environ.get("OPENFLOW_DATA_DIR"):
        yield
        return
    os.environ["OPENFLOW_DATA_DIR"] = str(tmp_path_factory.mktemp("openflow-data"))
    from openflow_backend.db.database import init_db
    init_db()
    yield
