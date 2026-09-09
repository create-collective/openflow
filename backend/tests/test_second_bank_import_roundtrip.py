"""A four-behaviour key read off the board survives import to the DB and re-encoding, byte for byte.

The two halves of this were each covered -- test_second_bank.py pins the decode, and
test_four_behaviour_roundtrip.py pins DB rows -> records -- but nothing ran the whole path
through keymap_import.import_read, and on 2026-09-09 that path was wrongly written up as an
open gap. It is not: the import stores whatever behaviours the decoder produces, so double_tap
and tap_hold land as rows, and desired_from_db turns them back into the second-bank record.
This test makes that impossible to lose quietly. No hardware.
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
from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402

# The exact WRITE_LAYER_DATA payload NayaFlow sent on 2026-09-03 (device/out/doubletap.pcap):
# key 0x49 tap B / hold Z, and its second bank 0x9b double-tap X / tap+hold Y.
CAPTURED = bytes.fromhex("00491018c80003010100c8001d0007000000000005000700000000"
                         "009b1018c80003010100c8001c000700000000001b00070000000000")


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, order_id INT, state TEXT, icon_id TEXT, author_name TEXT,
                               description TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, profile_id TEXT, id TEXT, updated_at TEXT,
                             created_at TEXT, animation_id TEXT, module_led_left TEXT, module_led_right TEXT);
        CREATE TABLE keys (color_hex TEXT, position_id INT, layer_id TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE key_bindings (context TEXT, action_code TEXT, action_type TEXT, behavior TEXT,
                                   key_id TEXT, id TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_configs (id TEXT, name TEXT, type TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT, module_config_id TEXT,
                                             binding_location TEXT, state TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE settings (correlation_id TEXT, value TEXT);
        CREATE TABLE module_bindings (id TEXT, module_config_id TEXT, behavior TEXT, action_type TEXT, action_code TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
    """)
    return conn


def _import(conn):
    recs = kr.parse_records(CAPTURED[1:])
    read = {"layers": {0: recs}, "led": {0: []},
            "layer_uuids": {0: "0cb76a71-1d42-43c8-8b4e-ab1c521695c9"}, "layer_animations": {0: 0}, "bays": {}}
    with mock.patch.object(ki, "connect", lambda: KeepOpen(conn)):
        return ki.import_read(read, "probe", {}), {p: (t, v) for p, t, v in recs}


def test_import_stores_all_four_behaviours():
    conn = _db()
    _import(conn)
    rows = {r["behavior"]: (r["action_type"], r["action_code"]) for r in conn.execute(
        "SELECT b.behavior, b.action_type, b.action_code FROM key_bindings b JOIN keys k ON b.key_id=k.id "
        "WHERE k.position_id = 0x49")}
    assert rows == {"press": ("key", "B"), "hold": ("key", "Z"),
                    "double_tap": ("key", "X"), "tap_hold": ("key", "Y")}, rows
    print("  key 0x49 -> press B, hold Z, double_tap X, tap_hold Y")


def test_reflash_reproduces_both_records_byte_for_byte():
    conn = _db()
    out, captured = _import(conn)
    d = F.desired_from_db(conn, out["profileId"])
    for pos in (0x49, 0x9B):
        assert d.layers[0].get(pos) == captured[pos], f"{pos:#04x}: {d.layers[0].get(pos)}"
    print("  desired_from_db rebuilds 0x49 and 0x9b exactly as NayaFlow wrote them")


def test_a_key_with_no_second_bank_stays_that_way():
    """The other direction of the same rule: importing a plain key must not invent a shadow."""
    conn = _db()
    out, _c = _import(conn)
    conn.execute("DELETE FROM key_bindings WHERE behavior IN ('double_tap', 'tap_hold')")
    conn.commit()
    d = F.desired_from_db(conn, out["profileId"])
    assert 0x9B not in d.layers[0]
    print("  without double-tap rows there is no second-bank record")


if __name__ == "__main__":
    for fn in (test_import_stores_all_four_behaviours, test_reflash_reproduces_both_records_byte_for_byte,
               test_a_key_with_no_second_bank_stays_that_way):
        print(fn.__name__)
        fn()
    print("\nOK")
