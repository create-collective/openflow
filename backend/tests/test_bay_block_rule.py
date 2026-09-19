"""A module bay block is one colour from the layer's module colour, never from key rows 88-96.

Derived from NayaFlow's own flashes on 2026-09-09 (docs/plan-status.md, "The bay mapping"): the
right bay 112-135 and the left bay 88-111 are each painted from one module colour, and the
values NayaFlow stores at its key positions 90-96 never reach the board as colours. OpenFlow's
planner, on the other hand, let key rows 88-96 -- leftovers from an old import -- outrank both
the module colour and the board, which would have striped the left bay purple and orange over
green. The rule now:

  * desired_from_db collects key colours for positions 0-87 only (keys + the two edge bars);
  * a layer with a module colour paints its whole 24-LED block;
  * a layer without one carries the board's block through untouched;
  * a read from the keyboard fills the layer's module colours from LEDs 88 and 112, and does
    not store 88-135 as key colours at all.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import keymap_import as ki  # noqa: E402
from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

GREEN, RED, MINT, PURPLE = (120, 100), (0, 100), (157, 87), (273, 100)
UNSET = (0, kr.UNSET_SATURATION)


def _db(module_left=None, module_right=None):
    """One layer; every key 0-96 coloured orange, as an old import would leave them."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE profiles (id TEXT, name TEXT, order_id INT);
        CREATE TABLE layers (id TEXT, order_id INT, profile_id TEXT, animation_id TEXT,
                             module_led_left TEXT, module_led_right TEXT);
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
    conn.execute("INSERT INTO layers VALUES ('L0', 0, 'P0', 'solid', ?, ?)", (module_left, module_right))
    for pos in range(97):
        conn.execute("INSERT INTO keys VALUES (?, 'L0', ?, '#ffa200')", (str(uuid.uuid4()), pos))
    conn.commit()
    return conn


def _board():
    """Layer 0 as read: keys white, left bay green with two mint stragglers, right bay red."""
    led = {}
    for i in range(136):
        led[i] = GREEN if 88 <= i < 112 else RED if i >= 112 else (0, 0)
    led[90] = led[95] = MINT
    d = F.DesiredState(layers={0: {}}, leds={0: led})
    return d


def _written(desired, current):
    plan = F.compute_plan(desired, current, full=True)
    # The full 136-record map is two writes now (SCRUM-100); read every part of the first
    # layer, not just the first write.
    ops = [op for op in plan if op.sub == R.WRITE_LED_MAP_DATA]
    layer = ops[0].payload[0]
    body = b"".join(op.payload[1:] for op in ops if op.payload[0] == layer)
    return {body[i]: (body[i + 1] | (body[i + 2] << 8), body[i + 3]) for i in range(0, len(body), 4)}


def test_key_rows_past_87_never_become_led_colours():
    d = F.desired_from_db(_db())
    assert max(d.leds[0]) == 87, f"key rows past 87 leaked into the LED map: {sorted(d.leds[0])[-3:]}"
    assert all(i in d.leds[0] for i in range(0, 88))
    print("  desired_from_db keeps colours for 0-87 only")


def test_no_module_colour_carries_the_boards_block_through():
    got = _written(F.desired_from_db(_db()), _board())
    assert got[90] == MINT and got[95] == MINT, "the board's own block values must survive"
    assert all(got[i] == GREEN for i in range(88, 112) if i not in (90, 95))
    assert all(got[i] == RED for i in range(112, 136))
    assert got[87] == kr.hex_to_hue_sat("#ffa200"), "the edge bar still comes from the profile"
    print("  no module colour -> both blocks exactly as the board holds them")


def test_a_module_colour_paints_the_whole_block_over_the_key_rows():
    got = _written(F.desired_from_db(_db(module_left="#0000ff")), _board())
    assert all(got[i] == (240, 100) for i in range(88, 112)), "left block not painted as one colour"
    assert all(got[i] == RED for i in range(112, 136)), "right block must be untouched"
    print("  left module colour -> 88-111 blue, stragglers included; right bay untouched")


def test_decode_reports_module_colours_from_the_first_led_of_each_block():
    led = [(i, *GREEN) if 88 <= i < 112 else (i, *RED) if i >= 112 else (i, 0, 0) for i in range(136)]
    out = kr.decode_keymap({"layers": {0: []}, "led": {0: led}}, {})
    assert out["_module_colours"][0] == {"left": "#00ff00", "right": "#ff0000"}
    assert max(out["_colors"][0]) == 87, "88-135 must not be reported as key colours"
    led[88] = (88, *UNSET)
    out = kr.decode_keymap({"layers": {0: []}, "led": {0: led}}, {})
    assert out["_module_colours"][0]["left"] is None, "the unset sentinel is not a colour"
    print("  decode: module colours from 88 / 112, key colours stop at 87")


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def test_a_board_read_fills_the_layers_module_colours():
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
    """)
    led = [(i, *GREEN) if 88 <= i < 112 else (i, *RED) if i >= 112 else (i, 0, 0) for i in range(136)]
    read = {"layers": {0: [(0x00, R.KEY_PRESS, R.encode_keypress("key", "A"))]}, "led": {0: led},
            "layer_uuids": {0: "0cb76a71-1d42-43c8-8b4e-ab1c521695c9"}, "layer_animations": {0: 3}, "bays": {}}
    with mock.patch.object(ki, "connect", lambda: KeepOpen(conn)):
        ki.import_read(read, None, {})
    row = conn.execute("SELECT module_led_left, module_led_right, animation_id FROM layers").fetchone()
    assert (row["module_led_left"], row["module_led_right"]) == ("#00ff00", "#ff0000")
    assert row["animation_id"] == "swirl", "byte 3 is swirl in the layer list"
    colours = {r[0]: r[1] for r in conn.execute("SELECT position_id, color_hex FROM keys")}
    assert colours[88] == ki.UNSET_COLOR and colours[96] == ki.UNSET_COLOR, "88-96 must not receive LED colours"
    assert colours[0] == "#ffffff"
    print("  import: module_led_left/right filled from the bays, key rows 88-96 left unset")


if __name__ == "__main__":
    for fn in (test_key_rows_past_87_never_become_led_colours,
               test_no_module_colour_carries_the_boards_block_through,
               test_a_module_colour_paints_the_whole_block_over_the_key_rows,
               test_decode_reports_module_colours_from_the_first_led_of_each_block,
               test_a_board_read_fills_the_layers_module_colours):
        print(fn.__name__)
        fn()
    print("\nOK")
