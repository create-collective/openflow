"""Two status caches, because the two pages read different amounts.

Device Manager's refresh is deliberately shallow -- firmware, battery, docked module. The
Information page also asks for the BLE identity block, which costs five more round trips per
half. Both pages paint from cache on mount so navigating away and back does not re-open the
serial port to ask what we already know.

Sharing ONE cache row breaks that: a shallow refresh from Device Manager would overwrite the
BLE block and empty half of the Information page. Merging the two rows would be worse than
either -- the BLE fields would carry an older timestamp than the rest of the same card while
being presented as one reading, which is the exact class of quiet lie this project keeps
finding. So there are two rows, each with its own honest "as of", and a deep read writes both
because it genuinely contains everything a shallow read would have, taken at the same moment.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import device_state as ds    # noqa: E402


class KeepOpen:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE settings (
        id INTEGER PRIMARY KEY, value TEXT, correlation_id TEXT, type TEXT,
        created_at TEXT, updated_at TEXT)""")
    return conn


def _patched(conn):
    return mock.patch.object(ds, "connect", lambda: KeepOpen(conn))


SHALLOW = [{"side": "left", "connected": True, "firmwareVersion": "3.41.0"}]
DEEP = [{"side": "left", "connected": True, "firmwareVersion": "3.41.0",
         "bleAddress": "C5:F4:36:95:3D:3B", "ble": {"pairAddress": "F3:69:F2:DE:F6:9C"}},
        {"side": "right", "connected": True, "firmwareVersion": "3.41.0",
         "bleAddress": "F3:69:F2:DE:F6:9C", "ble": {"pairAddress": "C5:F4:36:95:3D:3B"}}]


def test_a_shallow_refresh_does_not_wipe_the_ble_block():
    """The regression this design exists to prevent."""
    conn = _db()
    with _patched(conn):
        ds.save_status(DEEP, deep=True)
        ds.save_status(SHALLOW)                      # Device Manager hits Refresh
        got = ds.load_status(deep=True)
    assert got["halves"] is not None, "the deep cache was emptied by a shallow read"
    assert got["halves"][0].get("ble"), "the BLE block is gone"


def test_a_deep_read_also_satisfies_the_shallow_cache():
    """It is the same reading, taken at the same moment, with more in it."""
    conn = _db()
    with _patched(conn):
        ds.save_status(DEEP, deep=True)
        shallow = ds.load_status()
    assert shallow["halves"] == DEEP
    assert shallow["deep"] is True


def test_the_two_caches_keep_their_own_timestamps():
    conn = _db()
    with _patched(conn):
        ds.save_status(DEEP, deep=True)
        deep_at = ds.load_status(deep=True)["at"]
        ds.save_status(SHALLOW)
        assert ds.load_status(deep=True)["at"] == deep_at, "the deep row's 'as of' moved"


def test_a_shallow_read_is_not_labelled_deep():
    """The flag is what lets the UI say whether Bluetooth data is available at all."""
    conn = _db()
    with _patched(conn):
        ds.save_status(SHALLOW)
        assert ds.load_status()["deep"] is False


def test_empty_cache_is_shaped_like_a_full_one():
    """The page keys off .halves; a differently shaped miss would render as a blank page."""
    conn = _db()
    with _patched(conn):
        got = ds.load_status(deep=True)
    assert set(got) >= {"halves", "at", "deep"} and got["halves"] is None, got
