"""What the flash writes to a module, the read must call the same profile. Every time.

A read that finds a module slot matching no saved profile keeps it as "<name> (on board)". That is
right when the user changed the profile after flashing it. It is a BUG when nothing was edited:
the write and the read disagree about what the profile says, and every read (and the check after
every flash) mints another copy. Beta testers ended up with piles of them (2026-09-26 audit: 11 of
19 module profiles in the owner's own data were copies, several differing from their original
only by an empty pinch).

So this runs the real path end to end, per profile: the flash planner (flash.apply_module_layout
-> module_layout.overlay / encode_axis) writes a slot, and the read matcher (rest._build_entries
-> _compare -> _decode_field / _same_action) must find that exact profile with nothing differing:

  * every stock profile, unedited
  * every action a gesture can be given, on every gesture of every module
  * every pair on every axis, plain and inverted, and each half split onto a key or a direction
  * an axis or gesture cleared to unbound
  * a capture flashed back to the board it came from

In-memory SQLite only; every connect() the code under test makes is patched onto it. No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
import uuid as U
from pathlib import Path
from unittest import mock

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest                                  # noqa: E402
from openflow_backend.db import module_profiles as mp, userdata        # noqa: E402
from openflow_backend.device import actions_catalog as AC              # noqa: E402
from openflow_backend.device import flash as F                         # noqa: E402
from openflow_backend.device import module_actions as MA               # noqa: E402
from openflow_backend.device import module_fields as MF                # noqa: E402
from openflow_backend.device import module_layout as ml                # noqa: E402
from openflow_backend.device import remap as R                         # noqa: E402

TYPES = ("TOUCH", "TRACK", "TUNE")
STOCK = {"TOUCH": ("TOUCH_WINDOWS",), "TRACK": ("TRACK_LEFT", "TRACK_RIGHT"), "TUNE": ("TUNE",)}


class KeepOpen:
    def __init__(self, c): self._c = c
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


SCHEMA = """
CREATE TABLE module_configs (name TEXT, type TEXT, size INT, order_id INT, icon_id TEXT, variant TEXT,
  captured_from TEXT, id TEXT, updated_at TEXT, created_at TEXT);
CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT, behavior TEXT, invert INT,
  threshold INT, direction TEXT, mode INT, module_config_id TEXT, id TEXT, updated_at TEXT, created_at TEXT);
CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT, module_config_id TEXT,
  binding_location TEXT, state TEXT, updated_at TEXT, created_at TEXT);
CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT, type TEXT,
  updated_at TEXT, created_at TEXT);
CREATE TABLE layers (id TEXT, name TEXT, order_id INT, profile_id TEXT);
"""


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _profile(c, mtype, rows, *, name="P", settings=None):
    """rows: [(behavior, code, action_type, direction, invert)]. Backfilled the way the app
    backfills every profile it shows, so the rows are the ones a user would really have."""
    cid = str(U.uuid4())
    c.execute("INSERT INTO module_configs VALUES (?,?,0,0,NULL,NULL,NULL,?,'','')", (name, mtype, cid))
    for beh, code, atype, d, inv in rows:
        c.execute("INSERT INTO module_bindings VALUES (NULL,?,?,?,?,0,?,0,?,?,'','')",
                  (code, atype, beh, inv, d, cid, str(U.uuid4())))
    for k, v in (settings or {}).items():
        c.execute("INSERT INTO module_settings VALUES (?,?,?,'app','','')", (cid, k, v))
    userdata._ensure_gesture_slots(c)
    return cid


def _stock_rows(key):
    return [(b, v["action_code"], v["action_type"], "+", 0)
            for b, v in sorted(mp._STOCK[key]["bindings"].items())]


def _nayaflow_slot(mtype):
    """A slot the way a NayaFlow flash leaves one: a speed setting, and a keypress of nothing in
    every gesture field. The axes are empty."""
    out = {0x00: (R.KEY_PRESS, bytes([10]))}
    for _g, i in MF.writable_fields(mtype).items():
        out[i] = (R.KEY_PRESS, bytes(4))
    return out


def _read(board, cid, mtype, slot=1):
    lst = R.encode_module_config_list([(slot, slot, ml.MODULE_TYPE_CODE[mtype], R.layer_uuid_bytes(cid))]).hex()
    return {"list": lst, "by_uuid": {cid: slot},
            "slots": {slot: [{"field": i, "type": t, "value": v.hex()} for i, (t, v) in board.items()]}}


def _flash(c, mtype, cid, board):
    """The real planner, over a board whose slot 1 already carries this profile's uuid."""
    c.execute("DELETE FROM layers")
    c.execute("DELETE FROM module_config_bindings")
    c.execute("INSERT INTO layers VALUES ('L0','Layer 0',0,'KP')")
    c.execute("INSERT INTO module_config_bindings VALUES ('KP','L0',?,?,NULL,'','')",
              (cid, f"{mtype.lower()}:keyboard_left"))
    d = F.DesiredState(profile_id="KP", layers={0: {}})
    F.apply_module_layout(d, c, _read(board, cid, mtype))
    return d.modules.get(1, board)


def _entry(c, board, cid, mtype):
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(c)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(c)):
        return rest._build_entries(_read(board, cid, mtype))[0]


def _drift(e):
    return [(g["gesture"], g.get("half"), g["app"], g["device"]) for g in e["gestures"] if g["differs"]]


def _round_trip(mtype, rows, board=None, settings=None):
    """Flash a profile made of `rows`, read it back: [] when the read names it with no drift."""
    c = _db()
    cid = _profile(c, mtype, rows, settings=settings)
    written = _flash(c, mtype, cid, board if board is not None else _nayaflow_slot(mtype))
    e = _entry(c, written, cid, mtype)
    if e.get("matched") == cid and e["differs"] == 0:
        return []
    return _drift(e) or [("matched", e.get("matched"), cid, e["differs"])]


# --- the palette ------------------------------------------------------------------------------ #

def _singles():
    """Every single action a gesture can be given: the key palette's key-shaped actions and the
    module palette's own, minus pairs, 'none' and the LED codes pinned below."""
    out = set()
    for tab in AC.get_catalog()["tabs"]:
        for cat in tab["categories"]:
            for a in cat["actions"]:
                at = a.get("actionType") or a.get("type")
                if at in ("key", "modifier", "shortcut_alias", "mouse", "LED"):
                    out.add(a["code"])
    for a in MA.MODULE_ACTIONS:
        if a["actionType"] not in ("value", "none") and a["code"]:
            out.add(a["code"])
    return sorted(out)


def _pairs():
    return sorted({a["code"] for a in MA.MODULE_ACTIONS if a["actionType"] == "value"})


def _single_gestures(mtype):
    return [g for g in MF.writable_fields(mtype) if not MF.gesture_locked(mtype, g)]


# --- 1. stock profiles, unedited ---------------------------------------------------------------- #

@pytest.mark.parametrize("key", [k for t in TYPES for k in STOCK[t]])
def test_every_stock_profile_reads_back_as_itself(key):
    mtype = next(t for t in TYPES if key in STOCK[t])
    assert _round_trip(mtype, _stock_rows(key)) == []


@pytest.mark.parametrize("key", [k for t in TYPES for k in STOCK[t]])
def test_a_stock_profile_flashed_twice_still_reads_as_itself(key):
    """Flashing over our own write, not a NayaFlow one."""
    mtype = next(t for t in TYPES if key in STOCK[t])
    c = _db()
    cid = _profile(c, mtype, _stock_rows(key))
    board = _flash(c, mtype, cid, _flash(c, mtype, cid, _nayaflow_slot(mtype)))
    e = _entry(c, board, cid, mtype)
    assert (e.get("matched"), e["differs"], _drift(e)) == (cid, 0, [])


# --- 2. every single action on every gesture ------------------------------------------------------ #

@pytest.mark.parametrize("mtype", TYPES)
def test_every_single_action_round_trips_on_every_gesture(mtype):
    """Many gestures per profile at once, so the sweep stays a few hundred flashes."""
    stock = _stock_rows(STOCK[mtype][0])
    gestures, actions = _single_gestures(mtype), _singles()
    failures = []
    for start in range(0, len(actions), len(gestures)):
        chunk = dict(zip(gestures, actions[start:start + len(gestures)]))
        rows = [r for r in stock if r[0] not in chunk] + [(g, code, "key", "+", 0) for g, code in chunk.items()]
        failures += _round_trip(mtype, rows)
    assert failures == [], f"{len(failures)} single actions do not survive flash -> read:\n" + \
        "\n".join(map(str, failures[:60]))


# --- 3. every pair on every axis, plain and inverted; each half split ----------------------------- #

def _axis_cases():
    for mtype in TYPES:
        for axis in MF.splittable_axes(mtype):
            for pair in _pairs():
                for inv in (0, 1):
                    yield mtype, axis, pair, inv


@pytest.mark.parametrize("mtype,axis,pair,inv", list(_axis_cases()),
                         ids=lambda v: str(v).replace(" ", ""))
def test_every_pair_round_trips_on_every_axis(mtype, axis, pair, inv):
    rows = [r for r in _stock_rows(STOCK[mtype][0]) if r[0] != axis] + [(axis, pair, "value", "+", inv)]
    assert _round_trip(mtype, rows) == []


def _half_cases():
    directions = sorted(MF.MOTION_DIRECTIONS)
    for mtype in TYPES:
        for axis, half in MF.splittable_axes(mtype).items():
            for sign in ("-", "+"):
                for code in ("F13", "LCTRL + LSHIFT + V", *directions):
                    yield mtype, axis, sign, code


@pytest.mark.parametrize("mtype,axis,sign,code", list(_half_cases()),
                         ids=lambda v: str(v).replace(" ", ""))
def test_each_half_of_a_split_axis_round_trips(mtype, axis, sign, code):
    """Split the way set_axis_split stores it: the combined row stays, a half row is added."""
    rows = _stock_rows(STOCK[mtype][0])
    if not any(r[0] == axis for r in rows):
        rows.append((axis, MF.axis_halves(mtype)[axis]["default"], "value", "+", 0))
    rows.append((axis, code, "key", sign, 0))
    assert _round_trip(mtype, rows) == []


# --- 4. cleared to unbound ------------------------------------------------------------------------- #

@pytest.mark.parametrize("mtype,axis", [(t, a) for t in TYPES for a in MF.splittable_axes(t)])
def test_an_axis_cleared_to_unbound_round_trips(mtype, axis):
    """The editor's clear on an axis row stores "" -- the gesture does nothing."""
    rows = [r for r in _stock_rows(STOCK[mtype][0]) if r[0] != axis] + [(axis, "", "none", "+", 0)]
    assert _round_trip(mtype, rows) == []


@pytest.mark.parametrize("mtype,gesture", [(t, g) for t in TYPES for g in _single_gestures(t)])
def test_a_gesture_with_no_row_round_trips(mtype, gesture):
    """A profile with no row for a gesture (an old import, a hand-made file). The read calls that
    gesture unbound, so the flash has to write it unbound -- not leave the board's old value."""
    rows = [r for r in _stock_rows(STOCK[mtype][0]) if r[0] != gesture]
    c = _db()
    cid = _profile(c, mtype, rows)
    c.execute("DELETE FROM module_bindings WHERE module_config_id=? AND behavior=?", (cid, gesture))
    board = {**_nayaflow_slot(mtype), MF.writable_fields(mtype)[gesture]: (R.KEY_PRESS, R.encode_keypress("key", "F24"))}
    e = _entry(c, _flash(c, mtype, cid, board), cid, mtype)
    assert (e.get("matched"), e["differs"], _drift(e)) == (cid, 0, [])


@pytest.mark.parametrize("mtype,gesture", [(t, g) for t in TYPES for g in _single_gestures(t)])
def test_a_gesture_cleared_to_unbound_round_trips(mtype, gesture):
    rows = [r for r in _stock_rows(STOCK[mtype][0]) if r[0] != gesture] + [(gesture, "", "none", "+", 0)]
    assert _round_trip(mtype, rows) == []


# --- 5. a capture flashed back ---------------------------------------------------------------------- #

@pytest.mark.parametrize("key", [k for t in TYPES for k in STOCK[t]])
def test_a_capture_flashed_back_is_not_captured_again(key):
    """Read a board no profile matches -> the capture. Flash that capture onto the board: the read
    must name the capture, not mint "(on board) 2"."""
    mtype = next(t for t in TYPES if key in STOCK[t])
    c = _db()
    original = _profile(c, mtype, _stock_rows(key))
    board = _flash(c, mtype, original, _nayaflow_slot(mtype))
    # drift the board by hand: the first single gesture now presses F24
    g = _single_gestures(mtype)[0]
    board = {**board, MF.writable_fields(mtype)[g]: (R.KEY_PRESS, R.encode_keypress("key", "F24"))}
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(c)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(c)), \
         mock.patch.object(rest.dstate, "save", lambda m, s: {"at": "x"}):
        first = rest._module_diff(_read(board, original, mtype), None)
    cap = first["modules"][0]["matched"]
    assert cap and cap != original, "the drifted board should have been captured"
    userdata._ensure_gesture_slots(c)
    again = _flash(c, mtype, cap, board)
    e = _entry(c, again, cap, mtype)
    assert (e.get("matched"), e["differs"], _drift(e)) == (cap, 0, [])


# --- LED: the key's own record, on any gesture --------------------------------------------------------- #

def test_led_brightness_on_a_gesture_is_the_keys_own_led_record():
    """What NayaCore writes for its "LED Brightness" pinch pair, and what dims / brightens the
    backlight on the owner's Tune (tools/c14_tune_pinch_probe.py, 2026-09-26)."""
    assert ml._encode_gesture(0x19, "LED_BRIGHTNESS_UP") == (R.RGB_SYS, bytes.fromhex("0700000000000000"))
    assert ml._encode_gesture(0x14, "LED_BRIGHTNESS_DOWN") == (R.RGB_SYS, bytes.fromhex("0800000000000000"))


def test_an_empty_pinch_is_the_stock_state_on_both_sides():
    """NayaFlow ships pinch & spread empty and an empty pinch does nothing on the hardware, so a
    profile with no pinch row flashes it empty and reads an empty pinch as itself."""
    for mtype, axis in (("TUNE", "pinch&spread:tune:2_fingers"), ("TOUCH", "pinch&spread:touch:2_fingers")):
        rows = [r for r in _stock_rows(STOCK[mtype][0]) if r[0] != axis]
        c = _db()
        cid = _profile(c, mtype, rows)
        c.execute("DELETE FROM module_bindings WHERE module_config_id=? AND behavior=?", (cid, axis))
        written = _flash(c, mtype, cid, _nayaflow_slot(mtype))
        half = MF.axis_halves(mtype)[axis]
        assert written[half["-"]] == (R.NONE_BEH, b"") and written[half["+"]] == (R.NONE_BEH, b"")
        e = _entry(c, written, cid, mtype)
        assert (e.get("matched"), e["differs"]) == (cid, 0), _drift(e)
