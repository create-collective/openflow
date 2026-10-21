"""An empty key and a key with "No colour" must reach the keyboard as empty, not be skipped.

Two user reports (SCRUM-117, SCRUM-118, OpenFlow 0.7.0 on Linux, 2026-10-19), one cause. A key
the profile left empty was never put in the write plan, so the flash fell back to whatever the
board already had:

  * "No colour" on a key, then flash: the key kept its old colour. Real colours worked.
  * Unassign every function on a key, then flash: the key kept its old binding, and the next
    read (which reports the board faithfully) showed it again. Disabled worked, because it is
    written as an explicit NONE record.

Now an empty key is written as NONE (both banks) and "No colour" as the unset marker NayaFlow
writes for '#xxxxxx' (hue 0, saturation 150). Two limits, both tested here:

  * A key the board holds as TRANSPARENT is not cleared. A read stores a plain transparent key
    as an empty one, so every profile read off a keyboard has its transparent keys blank;
    clearing them would turn an upper layer's fall-through keys into dead keys.
  * A flash that clears most of a layer's bindings (a new, empty profile flashed as it is)
    needs a yes: the preview flags it and the route refuses it without allowBulkClear.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import types
import uuid
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402

from openflow_backend.api import rest                    # noqa: E402
from openflow_backend.device import flash as F           # noqa: E402
from openflow_backend.device import keymap_read as kr    # noqa: E402
from openflow_backend.device import remap as R           # noqa: E402

NONE = (R.NONE_BEH, b"")
TRANS = (R.TRANS, b"")
UNSET = (0, kr.UNSET_SATURATION)
A = (R.KEY_PRESS, R.encode_keypress("key", "A"))
B = (R.KEY_PRESS, R.encode_keypress("key", "B"))
# A double-tap shadow as NayaFlow leaves one (tests/test_second_bank_gc.py has its history).
SHADOW = (R.HOLD_TAP_ONEKEY, bytes.fromhex("c80003010101c8001c000700000000001b00070000000000"))

BOUND, EMPTY, SHADOWED, TRANSPARENT, ALREADY_NONE = 0x10, 0x11, 0x12, 0x13, 0x14
BAY = 0x4C


def _written(plan, layer=0) -> dict[int, tuple[int, bytes]]:
    body = b"".join(op.payload[1:] for op in plan
                    if op.sub == R.WRITE_LAYER_DATA and op.payload[0] == layer)
    return {p: (t, v) for p, t, v in kr.parse_records(body)}


def _leds(plan, layer=0) -> dict[int, tuple[int, int]]:
    out = {}
    for op in plan:
        if op.sub == R.WRITE_LED_MAP_DATA and op.payload[0] == layer and "wipe" not in op.label:
            body = op.payload[1:]
            out.update({body[i]: (body[i + 1] | (body[i + 2] << 8), body[i + 3])
                        for i in range(0, len(body), 4)})
    return out


def _board() -> F.DesiredState:
    """Layer 0 as a keyboard holds it: a bound key under each empty profile key we test."""
    return F.DesiredState(layers={0: {
        BOUND: A,
        EMPTY: A,
        SHADOWED: NONE, SHADOWED + F.SECOND_BANK: SHADOW,
        TRANSPARENT: TRANS, TRANSPARENT + F.SECOND_BANK: SHADOW,
        ALREADY_NONE: NONE,
        BAY: (4, b""),
    }}, leds={0: {i: (120, 100) for i in range(136)}})


# --- the real path, from the DB ---------------------------------------------------------- #

def _db(keys: dict[int, tuple[str | None, list[tuple[str, str, str]]]]) -> sqlite3.Connection:
    """{position: (color_hex, [(behavior, action_type, action_code), ...])} on one layer."""
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
    for pos, (colour, binds) in keys.items():
        kid = str(uuid.uuid4())
        conn.execute("INSERT INTO keys VALUES (?, 'L0', ?, ?)", (kid, pos, colour))
        for beh, at, code in binds:
            conn.execute("INSERT INTO key_bindings VALUES (?,?,?,?,?,NULL)",
                         (str(uuid.uuid4()), kid, beh, at, code))
    conn.commit()
    return conn


def _profile() -> F.DesiredState:
    """The profile the reports describe: one bound key, the rest left empty, a bay key row."""
    tap_b = [("press", "key", "B")]
    return F.desired_from_db(_db({
        BOUND: ("#ff0000", tap_b),
        EMPTY: ("#xxxxxx", []),
        SHADOWED: (None, []),
        TRANSPARENT: ("#xxxxxx", []),
        ALREADY_NONE: ("#xxxxxx", []),
        BAY: ("#xxxxxx", []),
    }))


def test_an_empty_key_is_written_as_none_over_a_board_binding():
    """SCRUM-118: unassign a key, flash, and the binding must be gone from the board."""
    written = _written(F.compute_plan(_profile(), _board(), full=True))
    assert written[BOUND] == B
    assert written[EMPTY] == NONE, f"the empty key kept the board's binding: {written[EMPTY]}"
    print("  an empty key over a board binding is written as NONE")


def test_an_empty_key_takes_its_double_tap_with_it():
    written = _written(F.compute_plan(_profile(), _board(), full=True))
    assert written[SHADOWED] == NONE
    assert written[SHADOWED + F.SECOND_BANK] == NONE, "a stale double-tap survived on an empty key"
    print("  an empty key's second bank is cleared as well")


def test_a_transparent_key_on_the_board_is_never_turned_into_a_dead_key():
    """A read stores a plain TRANS as no binding, so this key is blank in every profile read
    off a keyboard. Clearing it would break an upper layer's fall-through."""
    desired = _profile()
    written = _written(F.compute_plan(desired, _board(), full=True))
    assert written[TRANSPARENT] == TRANS, f"transparent key overwritten: {written[TRANSPARENT]}"
    assert written[TRANSPARENT + F.SECOND_BANK] == SHADOW, "a transparent key's second bank changed"
    assert TRANSPARENT not in desired.layers[0], "a transparent key must not be in the plan at all"
    print("  a transparent key is left exactly as the board has it")


def test_the_module_bays_are_untouched():
    written = _written(F.compute_plan(_profile(), _board(), full=True))
    assert written[BAY] == (4, b""), f"the bay binding at {BAY:#x} changed: {written[BAY]}"
    print("  an empty key row at a bay position does not touch the bay")


def test_an_unchanged_board_needs_no_layer_write():
    """An empty key over a board key that is already NONE changes nothing, so a profile that
    agrees with the board must still produce no layer write on a sync flash."""
    board = F.DesiredState(layers={0: {BOUND: B, TRANSPARENT: TRANS}})
    plan = F.compute_plan(_profile(), board, full=False)
    assert not [op for op in plan if op.sub == R.WRITE_LAYER_DATA], [op.label for op in plan]
    print("  a board that already agrees gets no layer write")


def test_no_colour_is_written_as_the_unset_marker():
    """SCRUM-117: 'No colour' over a coloured LED must clear it, as '#xxxxxx' and as NULL."""
    leds = _leds(F.compute_plan(_profile(), _board(), full=True))
    assert leds[BOUND] == kr.hex_to_hue_sat("#ff0000")
    for pos in (EMPTY, SHADOWED, TRANSPARENT, ALREADY_NONE):
        assert leds[pos] == UNSET, f"key {pos:#x} kept the board's colour {leds[pos]}"
    print("  'No colour' keys are written as the unset marker")


def test_a_layer_with_no_colours_at_all_still_writes_its_led_map():
    """Before, a layer whose keys were all uncoloured produced no LED write whatsoever."""
    desired = F.desired_from_db(_db({EMPTY: ("#xxxxxx", [("press", "key", "B")])}))
    leds = _leds(F.compute_plan(desired, _board(), full=False))
    assert leds and leds[EMPTY] == UNSET, "an all-uncoloured layer wrote no LED map"
    assert leds[100] == (120, 100), "an LED the app does not model must still pass through"
    print("  an all-uncoloured layer clears its key LEDs and passes the rest through")


# --- what the preview reports ------------------------------------------------------------- #

def test_cleared_keys_lists_only_keys_that_lose_something():
    cleared = F.cleared_keys(_profile(), _board())
    got = {c["position"]: c["was"] for c in cleared}
    assert set(got) == {EMPTY, SHADOWED}, got
    assert got[EMPTY] == ["A"], got[EMPTY]
    assert got[SHADOWED], "a double-tap-only key must say what it loses"
    print(f"  cleared: {got}")


def test_cleared_keys_is_empty_without_a_board_read():
    assert F.cleared_keys(_profile(), None) == []


def _full_board(n: int = 60) -> F.DesiredState:
    return F.DesiredState(layers={0: {p: A for p in range(n)}})


def _empty_profile(n: int = 60) -> F.DesiredState:
    return F.DesiredState(layers={0: {}}, empty_keys={0: set(range(n))})


def test_a_new_empty_profile_over_a_full_board_needs_a_yes():
    board = _full_board()
    bulk = F.bulk_clear_layers(F.cleared_keys(_empty_profile(), board), board)
    assert bulk == [{"layer": 0, "cleared": 60, "bound": 60}], bulk
    print("  a blank profile over a full layer is flagged")


def test_clearing_a_few_keys_does_not_ask():
    board = _full_board()
    desired = F.DesiredState(layers={0: {p: A for p in range(3, 60)}}, empty_keys={0: {0, 1, 2}})
    assert F.bulk_clear_layers(F.cleared_keys(desired, board), board) == []
    print("  clearing three keys of sixty asks nothing")


def test_a_small_layer_cleared_entirely_asks_once_it_reaches_the_minimum():
    board = _full_board(F.BULK_CLEAR_MIN_KEYS)
    desired = _empty_profile(F.BULK_CLEAR_MIN_KEYS)
    assert F.bulk_clear_layers(F.cleared_keys(desired, board), board), "a wiped layer was not flagged"


def test_the_confirmation_can_be_turned_off():
    board = _full_board()
    with mock.patch.object(F, "BULK_CLEAR_MIN_KEYS", None):
        assert F.bulk_clear_layers(F.cleared_keys(_empty_profile(), board), board) == []


# --- the route ------------------------------------------------------------------------------ #

app = FastAPI()
app.include_router(rest.router)
client = TestClient(app)


class FakeService:
    """A keyboard with sixty keys bound to A on layer 0."""
    def __init__(self):
        self._lock = threading.RLock()

    def read_keymap(self, side, serial=None):
        return {"layers": {0: [(p, A[0], A[1]) for p in range(60)]}, "led": {}, "layer_uuids": {}}

    def read_module_configs(self, side, serial=None):
        return None

    def _require_side(self, side, serial=None):
        return types.SimpleNamespace(port="COM0", side=side)

    def _dest_for_side(self, side):
        return 0x50

    def _transport_for(self, port, dest):
        return object()


class DummyConn:
    def close(self): pass


def _route(path, body, flash=None):
    with mock.patch.object(rest, "get_service", lambda: FakeService()), \
         mock.patch.object(rest, "db_connect", lambda: DummyConn()), \
         mock.patch.object(F, "desired_from_db", lambda conn, pid=None: _empty_profile()), \
         mock.patch.object(F, "flash", flash or F.flash), \
         mock.patch.object(rest.dstate, "clear", lambda reason: None):
        return client.post(path, json=body)


def test_the_route_refuses_a_bulk_clear_without_a_yes():
    sent = []
    r = _route("/rpc/flash", {"confirm": "FLASH", "profileId": "p"},
               flash=lambda *a, **kw: sent.append(1) or {"status": "verified"})
    assert r.status_code == 400, r.text
    assert "allowBulkClear" in r.text and "layer 0 (60 of 60)" in r.text, r.text
    assert not sent, "the refused flash still reached the write"
    print("  the route refuses a bulk clear, as a 400, before writing")


def test_the_route_flashes_a_bulk_clear_with_a_yes():
    r = _route("/rpc/flash", {"confirm": "FLASH", "profileId": "p", "allowBulkClear": True},
               flash=lambda *a, **kw: {"status": "sent-unverified"})
    assert r.status_code == 200, r.text


def test_the_preview_reports_cleared_keys_and_the_bulk_layers():
    r = _route("/rpc/flash-preview", {"profileId": "p"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["cleared"]) == 60 and body["cleared"][0]["was"] == ["A"], body["cleared"][:2]
    assert body["bulkClear"] == [{"layer": 0, "cleared": 60, "bound": 60}], body["bulkClear"]
    print("  the preview lists the cleared keys and flags the layer")
