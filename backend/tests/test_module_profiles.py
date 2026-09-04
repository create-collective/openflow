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
                                     icon_id TEXT, variant TEXT, captured_from TEXT, id TEXT,
                                     updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT,
                                      behavior TEXT, invert INT, threshold INT, direction TEXT,
                                      mode INT, module_config_id TEXT, id TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
        -- delete() checks this before removing a profile: a bay names the profile a
        -- layer runs, and dropping one underneath it is a foreign-key violation.
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT,
                                             module_config_id TEXT, binding_location TEXT,
                                             state TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE profiles (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE layers (id TEXT PRIMARY KEY, name TEXT, order_id INT, profile_id TEXT);
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


def test_new_profiles_append_below_their_own_variant():
    """Track is the case that matters: a right-hand profile must land under the existing
    right-hand ones, not at the top of the whole TRACK group."""
    conn = _db()
    with _patch(conn):
        mp.create("TRACK_LEFT", "Left A")
        mp.create("TRACK_RIGHT", "Right A")
        mp.create("TRACK_RIGHT")          # -> below Right A
        mp.create("TRACK_LEFT")           # -> below Left A, above the rights
    order = [r["name"] for r in conn.execute(
        "SELECT name FROM module_configs WHERE type='TRACK' ORDER BY order_id")]
    assert order[0] == "Left A" and order[1].startswith("Copy of Naya Track Left"), order
    assert order[2] == "Right A" and order[3].startswith("Copy of Naya Track Right"), order
    print(f"  {order}")


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
               test_new_profiles_append_below_their_own_variant,
               test_rotate_action_type_is_normalised,
               test_create_seeds_from_stock,
               test_second_profile_of_a_type_is_named_distinctly,
               test_rename_and_reject_empty,
               test_cannot_delete_the_last_profile_of_a_type,
               test_delete_removes_its_bindings_too):
        print(fn.__name__)
        fn()
    print("\nOK")


# --- import / export --------------------------------------------------------------------

def _io_db():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (name TEXT, type TEXT, size INT, order_id INT,
                                     icon_id TEXT, variant TEXT, captured_from TEXT, id TEXT,
                                     updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT,
                                      behavior TEXT, invert INT, threshold INT, direction TEXT,
                                      mode INT, module_config_id TEXT, id TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
    """)
    return conn


class _Keep:
    def __init__(self, c): self._c = c
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def test_a_split_axis_survives_export_and_import():
    """A split axis is three DB rows, two of which share direction "+". Exported flat they read
    as duplicates; the format nests the halves under `split` so the file says what it means."""
    import sqlite3
    from unittest import mock
    from openflow_backend.db import module_io

    conn = _io_db()
    cid = "c1"
    conn.execute("INSERT INTO module_configs (name,type,size,order_id,icon_id,variant,id,"
                 "updated_at,created_at) VALUES ('T','TUNE',0,0,NULL,'TUNE',?,'','')", (cid,))
    rows = [("mouse - SCROLL_UP - SCROLL_DOWN", "value", "vertical:tune:1_finger", "+"),
            ("F18", "key", "vertical:tune:1_finger", "-"),
            ("F17", "key", "vertical:tune:1_finger", "+"),
            ("F22", "key", "tap:tune:1_finger", "+")]
    for i, (code, atype, beh, d) in enumerate(rows):
        conn.execute("INSERT INTO module_bindings (action_code,action_type,behavior,invert,"
                     "threshold,direction,mode,module_config_id,id,updated_at,created_at) "
                     "VALUES (?,?,?,0,0,?,0,?,?,'','')", (code, atype, beh, d, cid, f"r{i}"))
    conn.commit()

    with mock.patch.object(module_io, "connect", lambda: _Keep(conn)):
        doc = module_io.export_profile(cid)
        axis = doc["bindings"]["vertical:tune:1_finger"]
        assert axis["actionCode"] == "mouse - SCROLL_UP - SCROLL_DOWN", "the combined row"
        assert axis["split"] == {"-": {"actionType": "key", "actionCode": "F18"},
                                 "+": {"actionType": "key", "actionCode": "F17"}}
        assert "split" not in doc["bindings"]["tap:tune:1_finger"], "a plain gesture has no halves"
        assert doc["moduleType"] == "TUNE" and doc["bindings"]

        back = module_io.import_profile(doc)
        got = {(r["behavior"], r["direction"]): r["action_code"] for r in conn.execute(
            "SELECT behavior, direction, action_code FROM module_bindings WHERE module_config_id=?",
            (back["id"],))}
    assert got[("vertical:tune:1_finger", "-")] == "F18"
    assert got[("vertical:tune:1_finger", "+")] in ("F17", "mouse - SCROLL_UP - SCROLL_DOWN")
    assert got[("tap:tune:1_finger", "+")] == "F22"
    assert back["name"] == "T 2", "an import never overwrites; the name is numbered"
    print(f"  round-tripped; imported as {back['name']!r}")


def test_module_type_is_required_and_checked():
    """It decides which module the profile belongs to and cannot be inferred -- Touch and Tune
    share gesture names, so a guess would quietly misfile the profile."""
    from openflow_backend.db import module_io as M

    for doc, expect in [
        ({"bindings": {"tap:tune:1_finger": {"actionType": "key", "actionCode": "A"}}}, "moduleType is required"),
        ({"moduleType": "TRACKPAD", "bindings": {"x": {}}}, "unknown moduleType"),
        ({"moduleType": "TUNE"}, "bindings must be"),
        ({"moduleType": "TUNE", "bindings": {}}, "bindings must be"),
        ({"format": "something.else", "moduleType": "TUNE", "bindings": {"a": {}}}, "not a module profile"),
        ({"moduleType": "TUNE", "bindings": {"tap:touch:4_fingers": {"actionType": "key", "actionCode": "A"}}},
         "is moduleType right?"),
    ]:
        try:
            M.import_profile(doc)
            raise AssertionError(f"should have been refused: {doc}")
        except M.ProfileFormatError as e:
            assert expect in str(e), f"{expect!r} not in {e}"
    print("  every malformed document is refused by name")
