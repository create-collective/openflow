"""Copying a layer between profiles must re-point its layer-switch bindings.

A layer-switch binding stores the TARGET LAYER'S UUID, and those layers are not part of a
single-layer export. Before this, a copied layer kept the source profile's uuids: the UI showed
the key as an unresolved "?" and a flash would have written a layer index the profile may not
even have.

The device stores a switch as a layer INDEX, so order is the meaningful identity -- the export
carries each referenced layer's order and the import resolves it against the destination
profile's layer at that same position.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
import uuid as uuidlib
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import profiles as prof  # noqa: E402


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, order_id INT, state TEXT, icon_id TEXT,
                               author_name TEXT, description TEXT, id TEXT,
                               updated_at TEXT, created_at TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, profile_id TEXT, icon_id TEXT,
                             animation_id TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE keys (color_hex TEXT, position_id INT, layer_id TEXT, id TEXT,
                           updated_at TEXT, created_at TEXT);
        CREATE TABLE key_bindings (context TEXT, action_code TEXT, action_type TEXT,
                                   behavior TEXT, key_id TEXT, id TEXT,
                                   updated_at TEXT, created_at TEXT);
        CREATE TABLE macros (name TEXT, type TEXT, icon_id TEXT, order_id INT, id TEXT,
                             updated_at TEXT, created_at TEXT);
        CREATE TABLE macro_steps (macro_id TEXT, order_id INT, action_code TEXT,
                                  action_type TEXT, delay INT, id TEXT,
                                  updated_at TEXT, created_at TEXT);
    """)
    ids = {}
    for pname, layers in (("SOURCE", ["S0", "S1", "S2"]), ("TARGET", ["T0", "T1", "T2"])):
        pid = str(uuidlib.uuid4())
        ids[pname] = {"id": pid, "layers": []}
        conn.execute("INSERT INTO profiles VALUES (?,0,'FLOW',NULL,NULL,NULL,?,'t','t')", (pname, pid))
        for order, lname in enumerate(layers):
            lid = str(uuidlib.uuid4())
            ids[pname]["layers"].append(lid)
            conn.execute("INSERT INTO layers VALUES (?,?,?,NULL,NULL,?,'t','t')",
                         (lname, order, pid, lid))
            for pos in range(3):
                conn.execute("INSERT INTO keys VALUES ('#xxxxxx',?,?,?,'t','t')",
                             (pos, lid, f"k-{lid}-{pos}"))
    # SOURCE layer 0, key 0 switches to SOURCE layer 2
    conn.execute("INSERT INTO key_bindings VALUES (NULL,?,?,'tap',?,?,'t','t')",
                 ("MO_LAYER_" + ids["SOURCE"]["layers"][2], "layer_polite_hold",
                  f"k-{ids['SOURCE']['layers'][0]}-0", str(uuidlib.uuid4())))
    conn.commit()
    return conn, ids


def test_switch_repoints_to_the_target_profiles_layer_of_the_same_order():
    conn, ids = _db()
    with mock.patch.object(prof, "connect", lambda: KeepOpen(conn)):
        prof.copy_layer(ids["SOURCE"]["layers"][0], ids["TARGET"]["id"])
    code = conn.execute(
        "SELECT b.action_code FROM key_bindings b JOIN keys k ON k.id=b.key_id "
        "JOIN layers l ON l.id=k.layer_id WHERE l.profile_id=? AND b.action_code LIKE 'MO_LAYER_%'",
        (ids["TARGET"]["id"],)).fetchone()["action_code"]
    target_uuid = code.removeprefix("MO_LAYER_")
    assert target_uuid == ids["TARGET"]["layers"][2], "switch did not re-point into the target"
    assert target_uuid != ids["SOURCE"]["layers"][2], "switch still points at the source profile"
    print("  a switch to source layer 2 becomes a switch to target layer 2")


def test_export_carries_the_order_of_referenced_layers():
    conn, ids = _db()
    with mock.patch.object(prof, "connect", lambda: KeepOpen(conn)):
        data = prof.export_layer(ids["SOURCE"]["layers"][0])
    assert data["layerRefs"] == {ids["SOURCE"]["layers"][2]: 2}, data.get("layerRefs")
    print("  the export records referenced layer uuid -> order")


def test_a_reference_with_no_counterpart_is_left_alone():
    """Copying into a profile with fewer layers must not invent a target."""
    conn, ids = _db()
    conn.execute("DELETE FROM layers WHERE id=?", (ids["TARGET"]["layers"][2],))
    conn.commit()
    with mock.patch.object(prof, "connect", lambda: KeepOpen(conn)):
        prof.copy_layer(ids["SOURCE"]["layers"][0], ids["TARGET"]["id"])
    code = conn.execute(
        "SELECT b.action_code FROM key_bindings b JOIN keys k ON k.id=b.key_id "
        "JOIN layers l ON l.id=k.layer_id WHERE l.profile_id=? AND b.action_code LIKE 'MO_LAYER_%'",
        (ids["TARGET"]["id"],)).fetchone()["action_code"]
    assert code.removeprefix("MO_LAYER_") == ids["SOURCE"]["layers"][2], \
        "a missing counterpart was silently remapped to some other layer"
    print("  no layer at that order -> the reference is left as-is, not guessed at")


if __name__ == "__main__":
    for fn in (test_switch_repoints_to_the_target_profiles_layer_of_the_same_order,
               test_export_carries_the_order_of_referenced_layers,
               test_a_reference_with_no_counterpart_is_left_alone):
        print(fn.__name__)
        fn()
    print("\nOK")
