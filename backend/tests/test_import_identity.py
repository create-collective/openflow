"""A re-read must update the profile it already knows, not create another one.

Names are not on the keyboard -- every layer-list and module-list entry carries a 16-byte UUID
and no name field. But that UUID is a stable identity, so a name CAN survive a round trip if we
keep it. We were discarding it twice: read_keymap took only the index byte from each 20-byte
entry, and the import then minted a fresh uuid4 per layer. The result was that one keyboard was
represented three times in the reference DB, with every user-given layer name lost each read.
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

from openflow_backend.db import keymap_import as ki  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

UUIDS = {0: "a10593a0-5b53-4177-a4a1-02018a631144",
         1: "6a6ae215-e1c7-466f-9941-aba6f75fd74e"}


def _schema(conn):
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, order_id INT, state TEXT, icon_id TEXT,
                               author_name TEXT, description TEXT, id TEXT,
                               updated_at TEXT, created_at TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, profile_id TEXT, id TEXT,
                             updated_at TEXT, created_at TEXT);
        CREATE TABLE keys (color_hex TEXT, position_id INT, layer_id TEXT, id TEXT,
                           updated_at TEXT, created_at TEXT);
        CREATE TABLE key_bindings (context TEXT, action_code TEXT, action_type TEXT,
                                   behavior TEXT, key_id TEXT, id TEXT,
                                   updated_at TEXT, created_at TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT,
                                             module_config_id TEXT, binding_location TEXT,
                                             state TEXT, updated_at TEXT, created_at TEXT);
    """)


def _read():
    """A minimal two-layer read: one bound key on layer 0."""
    return {
        "layers": {0: [(0x00, R.KEY_PRESS, R.encode_keypress("key", "A"))], 1: []},
        "led": {0: [], 1: []},
        "layer_uuids": dict(UUIDS),
        "bays": {0: {"track:keyboard_left": 4, "tune:keyboard_right": "transparent",
                     "float:keyboard_left": "disabled"}},
    }


class KeepOpen:
    """import_read closes its connection; the test still needs it afterwards."""
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _run(conn, name=None, read=None, slot_uuid=None):
    with mock.patch.object(ki, "connect", lambda: KeepOpen(conn)):
        return ki.import_read(read or _read(), name, slot_uuid)


def test_layer_rows_use_the_device_uuid():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first")
    ids = [r["id"] for r in conn.execute("SELECT id FROM layers ORDER BY order_id")]
    assert ids == [UUIDS[0], UUIDS[1]], ids
    print("  layer rows are keyed by the board's own uuids")


def test_a_reread_updates_instead_of_duplicating():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first")
    conn.execute("UPDATE layers SET name='Gaming' WHERE id=?", (UUIDS[0],))
    _run(conn)                                        # read the same board again
    profiles = conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"]
    layers = conn.execute("SELECT COUNT(*) c FROM layers").fetchone()["c"]
    assert profiles == 1, f"a re-read created {profiles} profiles"
    assert layers == 2, f"a re-read created {layers} layer rows"
    print("  re-reading the same board leaves one profile and two layers")


def test_a_user_given_layer_name_survives_a_reread():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first")
    conn.execute("UPDATE layers SET name='Gaming' WHERE id=?", (UUIDS[0],))
    _run(conn)
    name = conn.execute("SELECT name FROM layers WHERE id=?", (UUIDS[0],)).fetchone()["name"]
    assert name == "Gaming", f"the user's layer name became {name!r}"
    print("  a renamed layer keeps its name across a re-read")


def test_bindings_are_replaced_not_accumulated():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first")
    before = conn.execute("SELECT COUNT(*) c FROM key_bindings").fetchone()["c"]
    _run(conn)
    after = conn.execute("SELECT COUNT(*) c FROM key_bindings").fetchone()["c"]
    assert before == after == 1, f"bindings went {before} -> {after}"
    print("  a re-read replaces the bindings rather than stacking duplicates")


def test_an_unknown_board_still_makes_a_new_profile():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first")
    other = {**_read(), "layer_uuids": {0: "11111111-2222-3333-4444-555555555555", 1: "66666666-7777-8888-9999-000000000000"}}
    _run(conn, "second board", read=other)
    assert conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"] == 2
    print("  a board we have not seen still gets its own profile")


def test_bays_are_stored_and_replaced_on_reread():
    """The per-layer module bays: what the virtual board's module slots should show. A slot we
    have no config for is recorded as nothing rather than guessed at."""
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first", slot_uuid={4: "cfg-track-left"})
    rows = {r["binding_location"]: (r["module_config_id"], r["state"]) for r in
            conn.execute("SELECT binding_location, module_config_id, state FROM module_config_bindings")}
    assert rows["track:keyboard_left"] == ("cfg-track-left", None), rows
    assert rows["tune:keyboard_right"] == (None, "transparent"), rows
    assert rows["float:keyboard_left"] == (None, "disabled"), rows

    _run(conn, slot_uuid={4: "cfg-track-left"})          # re-read the same board
    n = conn.execute("SELECT COUNT(*) c FROM module_config_bindings").fetchone()["c"]
    assert n == 3, f"a re-read stacked bay rows ({n})"
    print("  bays stored with the right states, and replaced rather than duplicated")


def test_an_unknown_slot_is_not_invented():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; _schema(conn)
    _run(conn, "first", slot_uuid={})                     # no config list available
    locs = {r["binding_location"] for r in
            conn.execute("SELECT binding_location FROM module_config_bindings")}
    assert "track:keyboard_left" not in locs, "a bay was recorded for a slot we cannot resolve"
    assert {"tune:keyboard_right", "float:keyboard_left"} <= locs, "states should still be kept"
    print("  an unresolvable slot is skipped; transparent/disabled are still recorded")


if __name__ == "__main__":
    for fn in (test_layer_rows_use_the_device_uuid,
               test_a_reread_updates_instead_of_duplicating,
               test_a_user_given_layer_name_survives_a_reread,
               test_bindings_are_replaced_not_accumulated,
               test_an_unknown_board_still_makes_a_new_profile,
               test_bays_are_stored_and_replaced_on_reread,
               test_an_unknown_slot_is_not_invented):
        print(fn.__name__)
        fn()
    print("\nOK")


