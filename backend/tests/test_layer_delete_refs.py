"""Deleting a layer must not leave keys pointing at it.

A layer-switch binding stores the target layer's uuid. Delete that layer and the binding is
stranded -- and this is NOT merely cosmetic: the flash encoder used to resolve an unknown layer
to index 0, so a stranded switch silently became "switch to the base layer" on the keyboard
while the UI showed it as unresolved. A wrong binding the user cannot see is worse than a
visibly broken one.

They are cleared rather than repointed. There is no correct answer to "which layer did you mean
instead", and guessing would change what the keyboard does without saying so.
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

from openflow_backend.db import userdata as ud  # noqa: E402
from openflow_backend.device import flash as F  # noqa: E402


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, id TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, profile_id TEXT, id TEXT,
                             updated_at TEXT, created_at TEXT);
        CREATE TABLE keys (color_hex TEXT, position_id INT, layer_id TEXT, id TEXT,
                           updated_at TEXT, created_at TEXT);
        CREATE TABLE key_bindings (context TEXT, action_code TEXT, action_type TEXT,
                                   behavior TEXT, key_id TEXT, id TEXT,
                                   updated_at TEXT, created_at TEXT);
    """)
    pid = "P"
    conn.execute("INSERT INTO profiles VALUES ('p', 'P')")
    lids = []
    for order in range(3):
        lid = str(uuidlib.uuid4()); lids.append(lid)
        conn.execute("INSERT INTO layers VALUES (?,?,?,?,'t','t')", (f"L{order}", order, pid, lid))
        conn.execute("INSERT INTO keys VALUES ('#xxxxxx',0,?,?,'t','t')", (lid, f"k{order}"))
    # two keys switch to layer 2
    for i, src in enumerate((0, 1)):
        conn.execute("INSERT INTO key_bindings VALUES (NULL,?,?,'tap',?,?,'t','t')",
                     ("MO_LAYER_" + lids[2], "layer_polite_hold", f"k{src}", f"b{i}"))
    conn.commit()
    return conn, lids


def test_references_are_found_before_deleting():
    conn, lids = _db()
    refs = ud.layer_references(conn, lids[2])
    assert len(refs) == 2, refs
    assert {r["layerName"] for r in refs} == {"L0", "L1"}
    print("  2 keys found switching to the layer, on the layers that hold them")


def test_deleting_a_middle_layer_repoints_to_its_successor():
    """A key that meant "go to the third layer" should still mean that: whichever layer
    shifts up into the vacated position takes over the reference."""
    conn, lids = _db()
    # add a 4th layer and point the switches at layer 2 (the middle one about to go)
    conn.execute("INSERT INTO layers VALUES ('L3',3,'P','L3id','t','t')")
    conn.commit()
    with mock.patch.object(ud, "connect", lambda: KeepOpen(conn)):
        r = ud.delete_layer(lids[2])
    assert r["repointedReferences"] == 2 and r["clearedReferences"] == 0, r
    codes = {x["action_code"] for x in conn.execute(
        "SELECT action_code FROM key_bindings WHERE action_code LIKE 'MO_LAYER_%'")}
    assert codes == {"MO_LAYER_L3id"}, codes
    print("  both switches now point at the layer that took the vacated position")


def test_deleting_the_last_layer_clears_instead():
    """Nothing shifts into the vacated position, so there is genuinely nothing to point at."""
    conn, lids = _db()
    with mock.patch.object(ud, "connect", lambda: KeepOpen(conn)):
        r = ud.delete_layer(lids[2])
    assert r["clearedReferences"] == 2 and r["repointedReferences"] == 0, r
    left = conn.execute("SELECT COUNT(*) c FROM key_bindings WHERE action_code LIKE 'MO_LAYER_%'").fetchone()["c"]
    assert left == 0, f"{left} stranded binding(s) survived"
    print("  last layer deleted -> the bindings are cleared, not pointed somewhere arbitrary")


def test_an_unresolvable_switch_is_not_flashed_as_layer_zero():
    """The dangerous case: before this, a stale reference flashed as 'switch to layer 0'."""
    rows = [{"beh": "tap", "at": "layer_polite_hold", "ac": "MO_LAYER_" + str(uuidlib.uuid4())}]
    rec = F._binding_rows_to_record(rows, 200, 0, {})        # empty layer_order = unresolvable
    assert rec is None, f"an unresolvable switch encoded as {rec}"
    known = str(uuidlib.uuid4())
    rec = F._binding_rows_to_record(
        [{"beh": "tap", "at": "layer_polite_hold", "ac": "MO_LAYER_" + known}], 200, 0, {known: 2})
    assert rec is not None and rec[1] == F.R.encode_layer_param(2), "a resolvable switch broke"
    print("  unresolvable -> not written at all; resolvable -> still encodes its real index")


if __name__ == "__main__":
    for fn in (test_references_are_found_before_deleting,
               test_deleting_a_middle_layer_repoints_to_its_successor,
               test_deleting_the_last_layer_clears_instead,
               test_an_unresolvable_switch_is_not_flashed_as_layer_zero):
        print(fn.__name__)
        fn()
    print("\nOK")
