"""A bay names a profile of its own type or nothing.

A read once stored a Track profile's id in a Tune bay (the board's bay byte pointed at the slot
holding it), and the page then showed "Unknown profile" for a layer that should simply have
followed the base layer. Now the import never stores such a row, and the flash treats one that
exists as inherited, so a layer only ever departs from layer 0 where its picker really chose.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import keymap_import as kmi          # noqa: E402
from tests.test_flash_module_layout import BASE, TRACK_L, _desired  # noqa: E402


def test_the_flash_treats_a_wrong_typed_bay_as_inherited():
    clean, clean_layout = _desired({0: BASE, 1: {}})
    dirty, dirty_layout = _desired({0: BASE, 1: {"tune:keyboard_left": TRACK_L}})
    assert dirty_layout["bays"] == clean_layout["bays"]
    assert dirty_layout["allocated"] == clean_layout["allocated"]
    assert dirty.layers.keys() == clean.layers.keys()


def test_the_import_never_stores_a_wrong_typed_bay():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (id TEXT, type TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT, module_config_id TEXT,
                                             binding_location TEXT, state TEXT,
                                             updated_at TEXT, created_at TEXT);
    """)
    conn.execute("INSERT INTO module_configs VALUES ('track-1', 'TRACK')")
    conn.execute("INSERT INTO module_configs VALUES ('tune-1', 'TUNE')")
    read = {"bays": {"2": {"tune:keyboard_left": 5, "track:keyboard_left": 5, "touch:keyboard_left": 6}}}
    n = kmi._import_bays(conn, "p", {2: "l2"}, read, {5: "track-1", 6: "tune-1"}, "now")
    rows = {r["binding_location"]: r["module_config_id"]
            for r in conn.execute("SELECT binding_location, module_config_id FROM module_config_bindings")}
    assert n == 1
    assert rows == {"track:keyboard_left": "track-1"}   # the Track slot binds the Track bay only
