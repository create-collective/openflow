"""Creating, renaming and deleting module profiles.

A module can have several profiles and each layer picks one, so the app has to manage a set
rather than a single config per type. A new profile is seeded from the stock map so it is usable
the moment it exists -- an empty profile would flash a module that does nothing.

Track ships two stock variants because the module is ASYMMETRIC: flipping it to the other side
reverses the physical button order and the scroll direction. Either can occupy either bay.
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

from openflow_backend.db import module_profiles as mp  # noqa: E402


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (name TEXT, type TEXT, size INT, order_id INT,
                                     icon_id TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT,
                                      behavior TEXT, invert INT, threshold INT, direction TEXT,
                                      mode INT, module_config_id TEXT, id TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
    """)
    conn.commit()
    return conn


def _patch(conn):
    return mock.patch.object(mp, "connect", lambda: KeepOpen(conn))


def test_the_stock_track_buttons_are_the_real_defaults():
    """Confirmed by the device owner and matching the reference DB exactly. The recovered
    installer map has NO Track button entries, so it cannot be the source for these."""
    left = mp._STOCK["TRACK_LEFT"]["bindings"]
    right = mp._STOCK["TRACK_RIGHT"]["bindings"]
    got_l = [left[f"tap:track:button_{i}"]["action_code"] for i in (1, 2, 3, 4)]
    got_r = [right[f"tap:track:button_{i}"]["action_code"] for i in (1, 2, 3, 4)]
    assert got_l == ["M1", "M3", "M2", "M4"], got_l
    assert got_r == ["M4", "M2", "M3", "M1"], got_r
    assert got_l == got_r[::-1], "left/right should be mirrored -- the module is asymmetric"
    print(f"  track left {got_l}, right {got_r} -- mirrored")


def test_rotate_action_type_is_normalised():
    """NayaFlow stored Track Right's rotate as 'mouse' and Track Left's as 'value' for the
    identical action code."""
    for k in ("TRACK_LEFT", "TRACK_RIGHT"):
        assert mp._STOCK[k]["bindings"]["rotate:track"]["action_type"] == "value"
    print("  rotate:track is 'value' on both variants")


def test_create_seeds_from_stock():
    conn = _db()
    with _patch(conn):
        r = mp.create("TRACK_LEFT")
    assert r["bindings"] == len(mp._STOCK["TRACK_LEFT"]["bindings"]) > 0, "created an empty profile"
    rows = {x["behavior"]: x["action_code"] for x in
            conn.execute("SELECT behavior, action_code FROM module_bindings WHERE module_config_id=?", (r["id"],))}
    assert rows["tap:track:button_1"] == "M1"
    print(f"  a new Track (left) arrives with {r['bindings']} working bindings")


def test_second_profile_of_a_type_is_named_distinctly():
    conn = _db()
    with _patch(conn):
        a = mp.create("TRACK_LEFT")
        b = mp.create("TRACK_LEFT")
    assert a["name"] != b["name"], f"both profiles are called {a['name']!r}"
    print(f"  {a['name']!r} then {b['name']!r}")


def test_rename_and_reject_empty():
    conn = _db()
    with _patch(conn):
        r = mp.create("TUNE")
        mp.rename(r["id"], "  Media  ")
        name = conn.execute("SELECT name FROM module_configs WHERE id=?", (r["id"],)).fetchone()["name"]
        assert name == "Media", name
        for bad in ("", "   ", None):
            try:
                mp.rename(r["id"], bad)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad!r} as a name")
    print("  renaming trims, and an empty name is refused")


def test_cannot_delete_the_last_profile_of_a_type():
    conn = _db()
    with _patch(conn):
        only = mp.create("TUNE")
        try:
            mp.delete(only["id"])
        except ValueError as e:
            assert "only" in str(e).lower(), str(e)
        else:
            raise AssertionError("deleted the last Tune profile -- the module would be undriveable")
        second = mp.create("TUNE")
        mp.delete(second["id"])
    left = conn.execute("SELECT COUNT(*) c FROM module_configs WHERE type='TUNE'").fetchone()["c"]
    assert left == 1
    print("  the last profile of a type is protected; a second one deletes fine")


def test_delete_removes_its_bindings_too():
    conn = _db()
    with _patch(conn):
        a = mp.create("TOUCH_WINDOWS")
        b = mp.create("TOUCH_WINDOWS")
        mp.delete(b["id"])
    orphan = conn.execute("SELECT COUNT(*) c FROM module_bindings WHERE module_config_id=?",
                          (b["id"],)).fetchone()["c"]
    assert orphan == 0, f"{orphan} binding rows left behind"
    print("  deleting a profile takes its bindings with it")


if __name__ == "__main__":
    for fn in (test_the_stock_track_buttons_are_the_real_defaults,
               test_rotate_action_type_is_normalised,
               test_create_seeds_from_stock,
               test_second_profile_of_a_type_is_named_distinctly,
               test_rename_and_reject_empty,
               test_cannot_delete_the_last_profile_of_a_type,
               test_delete_removes_its_bindings_too):
        print(fn.__name__)
        fn()
    print("\nOK")
