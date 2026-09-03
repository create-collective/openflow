"""A four-behaviour key must survive DB -> device records -> decode, unchanged.

This is the round trip that matters for the UI: if a user sets tap/hold/double-tap/tap+hold in
OpenFlow, desired_from_db has to emit BOTH bank records, and reading them back has to land all
four on the same key. Before the second bank was understood, the write emitted only the primary
record and the read discarded the secondary one.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402

WANT = {"tap": ("key", "B"), "hold": ("key", "Z"),
        "double_tap": ("key", "X"), "tap_hold": ("key", "Y")}
POS = 0x49


def _db(behaviours):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE profiles (id TEXT, name TEXT, order_id INT);
        CREATE TABLE layers (id TEXT, order_id INT, profile_id TEXT);
        CREATE TABLE keys (id TEXT, layer_id TEXT, position_id INT, color_hex TEXT);
        CREATE TABLE key_bindings (id TEXT, key_id TEXT, behavior TEXT, action_type TEXT,
                                   action_code TEXT, context TEXT);
        CREATE TABLE settings (correlation_id TEXT, value TEXT);
        CREATE TABLE module_configs (id TEXT, type TEXT, name TEXT);
        CREATE TABLE module_bindings (id TEXT, module_config_id TEXT, behavior TEXT,
                                      action_type TEXT, action_code TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
    """)
    conn.execute("INSERT INTO profiles VALUES ('P0', 'test', 0)")
    conn.execute("INSERT INTO layers VALUES ('L0', 0, 'P0')")
    conn.execute("INSERT INTO keys VALUES ('K', 'L0', ?, NULL)", (POS,))
    for beh, (at, code) in behaviours.items():
        conn.execute("INSERT INTO key_bindings VALUES (?,?,?,?,?,NULL)",
                     (str(uuid.uuid4()), "K", beh, at, code))
    conn.commit()
    return conn


def test_all_four_are_written_to_both_banks():
    d = F.desired_from_db(_db(WANT))
    layer = d.layers[0]
    assert POS in layer, "primary record missing"
    assert POS + F.SECOND_BANK in layer, "secondary record missing -- double-tap would be lost"

    recs = [(p, t, v) for p, (t, v) in sorted(layer.items())]
    decoded = kr.decode_keymap({"layers": {0: recs}, "led": {}}, {})
    # the device calls the primary slot 'press'; the UI calls it 'tap' (documented alias)
    norm = lambda b: 'tap' if b == 'press' else b
    got = dict((norm(b), c) for b, _at, c in decoded[0][POS])
    assert got == {k: v[1] for k, v in WANT.items()}, got
    print(f"  4 behaviours -> 2 records ({POS:#04x}, {POS + F.SECOND_BANK:#04x}) -> back to 4: {got}")


def test_ui_spelling_of_tap_hold_is_accepted():
    """The UI slot id is 'tap+hold'; the device decoder says 'tap_hold'. Both must work."""
    alt = dict(WANT); alt["tap+hold"] = alt.pop("tap_hold")
    layer = F.desired_from_db(_db(alt)).layers[0]
    assert POS + F.SECOND_BANK in layer, "'tap+hold' spelling did not reach the second bank"
    print("  'tap+hold' and 'tap_hold' both map to the same slot")


def test_only_double_tap_still_writes_a_secondary_record():
    only = {"tap": ("key", "B"), "double_tap": ("key", "X")}
    layer = F.desired_from_db(_db(only)).layers[0]
    assert POS + F.SECOND_BANK in layer
    decoded = kr.decode_keymap(
        {"layers": {0: [(p, t, v) for p, (t, v) in sorted(layer.items())]}, "led": {}}, {})
    got = dict((b, c) for b, _at, c in decoded[0][POS])
    assert got.get("double_tap") == "X" and got.get("press") == "B"
    print("  a lone double-tap still produces its record (empty hold slot)")


def test_no_second_bank_binding_means_no_second_record():
    layer = F.desired_from_db(_db({"tap": ("key", "B"), "hold": ("key", "Z")})).layers[0]
    assert POS + F.SECOND_BANK not in layer, "wrote a secondary record for a key that has none"
    print("  tap+hold only -> no secondary record emitted")


if __name__ == "__main__":
    for fn in (test_all_four_are_written_to_both_banks,
               test_ui_spelling_of_tap_hold_is_accepted,
               test_only_double_tap_still_writes_a_secondary_record,
               test_no_second_bank_binding_means_no_second_record):
        print(fn.__name__)
        fn()
    print("\nOK")
