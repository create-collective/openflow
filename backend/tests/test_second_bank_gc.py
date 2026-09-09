"""A modelled key owns its second bank: a tap-only key must WRITE an empty double-tap slot.

Observed on hardware, not imagined (docs/nayaflow-verify-test-plan.md). Keys 53 and 73 once had
four behaviours; the profile was reduced to tap-only; every later flash from either app carried
the two stale shadows at 0x87 / 0x9b through, and NayaFlow's verify failed on exactly those
records ("Failed to verify written data", NayaCore log 2026-09-08 17:51). Clearing the two
slots by hand made the next NayaFlow flash verify. This test pins the rule that stops it
recurring: when the profile sets a key and has no double-tap / tap+hold for it, the plan writes
NONE at key + 0x52 -- and the verify checks it. Keys the profile does NOT set keep both banks
from the device, exactly as before.
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
from openflow_backend.device import remap as R  # noqa: E402

# The exact shadow NayaFlow left at 0x9b on 2026-09-03 (double-tap X / tap+hold Y), as read
# back on 2026-09-09 (device/out/verify-probe-before.json).
SHADOW = bytes.fromhex("c80003010101c8001c000700000000001b00070000000000")
KEY = 0x49
SHADOW_POS = KEY + F.SECOND_BANK          # 0x9b
OTHER = 0x35                              # a key the profile does NOT set; its shadow is 0x87
BAY = 0x4C
TAP_B = (R.KEY_PRESS, R.encode_keypress("key", "B"))


def _device() -> F.DesiredState:
    """Layer 0 as the board held it: both keys with a stale shadow, plus one bay."""
    return F.DesiredState(layers={0: {
        KEY: (R.LAYER_HOLD, R.encode_layer_param(2)),
        SHADOW_POS: (R.HOLD_TAP_ONEKEY, SHADOW),
        OTHER: (R.KEY_PRESS, R.encode_keypress("key", "BACKSPACE")),
        OTHER + F.SECOND_BANK: (R.HOLD_TAP_ONEKEY, SHADOW),
        BAY: (4, b""),
    }})


def _written(plan) -> dict[int, tuple[int, bytes]]:
    payload = next(op.payload for op in plan if op.sub == R.WRITE_LAYER_DATA)
    return {p: (t, v) for p, t, v in kr.parse_records(payload[1:])}


def test_tap_only_key_blanks_its_shadow():
    desired = F.DesiredState(layers={0: {KEY: TAP_B}})
    written = _written(F.compute_plan(desired, _device(), full=True))
    assert written[SHADOW_POS] == (R.NONE_BEH, b""), \
        f"stale shadow survived the flash: {written[SHADOW_POS]}"
    assert written[KEY] == TAP_B
    print(f"  key {KEY:#04x} set tap-only -> {SHADOW_POS:#04x} written as NONE")


def test_unmodelled_key_keeps_both_banks():
    desired = F.DesiredState(layers={0: {KEY: TAP_B}})
    written = _written(F.compute_plan(desired, _device(), full=True))
    assert written[OTHER] == (R.KEY_PRESS, R.encode_keypress("key", "BACKSPACE"))
    assert written[OTHER + F.SECOND_BANK] == (R.HOLD_TAP_ONEKEY, SHADOW), \
        "a key the profile does not set must keep its double-tap from the device"
    print(f"  key {OTHER:#04x} not in the profile -> both its banks carried through")


def test_four_behaviour_key_keeps_its_own_shadow():
    mine = R.encode_hold_tap(("key", "X"), ("key", "Y"), R.HOLD_TAP_ONEKEY, flavour=1, term=200)
    desired = F.DesiredState(layers={0: {KEY: TAP_B, SHADOW_POS: (R.HOLD_TAP_ONEKEY, mine)}})
    written = _written(F.compute_plan(desired, _device(), full=True))
    assert written[SHADOW_POS] == (R.HOLD_TAP_ONEKEY, mine), "the profile's own double-tap was blanked"
    print("  a profile WITH a double-tap writes it, not NONE")


def test_verify_covers_the_blanked_shadow():
    """The blank is added to `desired`, so diff_desired sees whether the board honoured it."""
    desired = F.DesiredState(layers={0: {KEY: TAP_B}})
    F.compute_plan(desired, _device(), full=True)
    assert desired.layers[0][SHADOW_POS] == (R.NONE_BEH, b"")

    still_there = _device()
    assert any(m["pos"] == SHADOW_POS for m in F.diff_desired(desired, still_there)), \
        "a shadow the board kept must fail the verify"
    cleared = _device()
    cleared.layers[0][SHADOW_POS] = (R.NONE_BEH, b"")
    assert not [m for m in F.diff_desired(desired, cleared) if m["pos"] == SHADOW_POS]
    print("  verify fails while the shadow remains and passes once it is NONE")


def test_bays_and_unset_keys_get_no_shadow_entry():
    desired = F.DesiredState(layers={0: {KEY: TAP_B, BAY: (4, b"")}})
    plan = F.compute_plan(desired, _device(), full=True)
    assert BAY + F.SECOND_BANK not in desired.layers[0], "a bay has no second bank"
    assert OTHER + F.SECOND_BANK not in desired.layers[0], "an unset key gained a NONE it should not"
    assert set(_written(plan)) == set(F.ALL_LAYER_POSITIONS), "payload must stay 0x00-0x9b"
    print("  only the keys the profile sets gain a second-bank entry")


def test_recovery_mode_blanks_it_too():
    """No device read: nothing to carry through, so the slot is NONE either way."""
    desired = F.DesiredState(layers={0: {KEY: TAP_B}})
    written = _written(F.compute_plan(desired, None, full=True))
    assert written[SHADOW_POS] == (R.NONE_BEH, b"")
    print("  recovery mode writes NONE there as well")


# --- the real path: desired_from_db ------------------------------------------------------- #

def _db(behaviours: dict) -> sqlite3.Connection:
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
    conn.execute("INSERT INTO keys VALUES ('K', 'L0', ?, NULL)", (KEY,))
    for beh, (at, code) in behaviours.items():
        conn.execute("INSERT INTO key_bindings VALUES (?,?,?,?,?,NULL)",
                     (str(uuid.uuid4()), "K", beh, at, code))
    conn.commit()
    return conn


def test_tap_only_from_the_db_blanks_the_board_shadow():
    desired = F.desired_from_db(_db({"tap": ("key", "B")}))
    assert SHADOW_POS not in desired.layers[0], "desired_from_db itself emits no second record"
    written = _written(F.compute_plan(desired, _device(), full=True))
    assert written[KEY] == TAP_B
    assert written[SHADOW_POS] == (R.NONE_BEH, b""), "the DB path still let the stale shadow through"
    print("  DB tap-only key over a board shadow -> shadow written as NONE")


def test_disabled_key_from_the_db_blanks_its_shadow_as_well():
    desired = F.desired_from_db(_db({"tap": ("none", "NONE")}))
    written = _written(F.compute_plan(desired, _device(), full=True))
    assert written[KEY] == (R.NONE_BEH, b"") and written[SHADOW_POS] == (R.NONE_BEH, b"")
    print("  disabling a key clears its double-tap slot too")


if __name__ == "__main__":
    for fn in (test_tap_only_key_blanks_its_shadow,
               test_unmodelled_key_keeps_both_banks,
               test_four_behaviour_key_keeps_its_own_shadow,
               test_verify_covers_the_blanked_shadow,
               test_bays_and_unset_keys_get_no_shadow_entry,
               test_recovery_mode_blanks_it_too,
               test_tap_only_from_the_db_blanks_the_board_shadow,
               test_disabled_key_from_the_db_blanks_its_shadow_as_well):
        print(fn.__name__)
        fn()
    print("\nOK")
