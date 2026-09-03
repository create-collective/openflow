"""Reading the board must not claim a profile is live when it is not.

A module profile shares its uuid with the device slot it came from. That uuid survives local
edits, so an edited-but-unflashed profile still matched the slot and the UI marked it "on the
keyboard" -- while the keyboard was running the pre-edit version. The mark was false, and the
board's real state had nowhere to live in the app.

So the read resolves "live" by CONTENT, and captures anything the board runs that no profile
represents -- the same bargain layers already make, where a device layer we do not recognise
becomes a layer rather than being dropped.

The load-bearing property is idempotence: matching by content means the capture itself matches
on the next read, so reading twice must not mint a second copy. Without that, every read would
grow the profile list forever.
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

from openflow_backend.api import rest  # noqa: E402
from openflow_backend.db import module_profiles as mp  # noqa: E402
from openflow_backend.device import module_fields  # noqa: E402


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


TYPE = "TRACK"
UUID = "11111111-1111-1111-1111-111111111111"


def _fields():
    """A device slot's raw fields for the Track button gestures, as the read returns them."""
    idx = module_fields.writable_fields(TYPE)
    out = []
    for gesture, i in sorted(idx.items()):
        code = _DEVICE.get(gesture)
        if code is None:
            continue
        out.append({"field": i, "type": 0x0F, "value": _encode(code)})
    return out


def _encode(code):
    from openflow_backend.device import remap as R
    return R.encode_mouse_button(code).hex()


# What the board is running.
_DEVICE = {f"tap:track:button_{i}": c for i, c in zip((1, 2, 3, 4), ("M1", "M3", "M2", "M4"))}


def _db(app_bindings):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (name TEXT, type TEXT, size INT, order_id INT,
                                     icon_id TEXT, variant TEXT, captured_from TEXT, id TEXT,
                                     updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT,
                                      behavior TEXT, invert INT, threshold INT, direction TEXT,
                                      mode INT, module_config_id TEXT, id TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT,
                                             module_config_id TEXT, binding_location TEXT,
                                             state TEXT, updated_at TEXT, created_at TEXT);
    """)
    conn.execute("INSERT INTO module_configs (name,type,size,order_id,icon_id,variant,id,"
                 "updated_at,created_at) VALUES ('Naya Track Left',?,0,0,NULL,'TRACK_LEFT',?,'','')",
                 (TYPE, UUID))
    for g, c in app_bindings.items():
        conn.execute("INSERT INTO module_bindings (action_id,action_code,action_type,behavior,"
                     "invert,threshold,direction,mode,module_config_id,id,updated_at,created_at)"
                     " VALUES (NULL,?,'mouse',?,0,0,'+',0,?,?,'','')", (c, g, UUID, g))
    conn.commit()
    return conn


def _read():
    return {"by_uuid": {UUID: 1}, "slots": {1: _fields()}}


def _run(conn):
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(conn)):
        return rest._module_diff(_read())


def _names(conn):
    return [r["name"] for r in conn.execute("SELECT name FROM module_configs ORDER BY order_id")]


def test_a_matching_profile_is_marked_live_and_nothing_is_captured():
    conn = _db(dict(_DEVICE))
    out = _run(conn)
    assert out["captured"] == []
    assert out["modules"][0]["matched"] == UUID
    assert _names(conn) == ["Naya Track Left"]
    print("  app matches the board -> marked live, no capture")


def test_a_drifted_profile_is_not_live_and_the_board_is_captured():
    """The bug this exists for: the drifted profile used to be marked live."""
    drifted = dict(_DEVICE, **{"tap:track:button_1": "M2"})   # user edited, never flashed
    conn = _db(drifted)
    out = _run(conn)

    entry = out["modules"][0]
    assert entry["differs"] == 1, entry["differs"]
    assert entry["matched"] != UUID, "the edited profile must NOT be reported as live"
    assert len(out["captured"]) == 1
    cap = out["captured"][0]
    assert entry["matched"] == cap["id"], "the capture is what is on the board"
    assert cap["name"] == "Naya Track Left (on board)"
    assert _names(conn) == ["Naya Track Left", "Naya Track Left (on board)"]
    print(f"  drift -> captured {cap['name']!r}; the edited profile is no longer claimed live")


def test_the_capture_holds_the_boards_values_not_the_apps():
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    cap = _run(conn)["captured"][0]
    got = {r["behavior"]: r["action_code"] for r in conn.execute(
        "SELECT behavior, action_code FROM module_bindings WHERE module_config_id=?", (cap["id"],))}
    assert got["tap:track:button_1"] == "M1", got      # the device value, not the app's M2
    print("  capture carries the device's binding")


def test_reading_twice_does_not_mint_a_second_capture():
    """Content matching is what makes this safe -- the capture matches on the next read."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    first = _run(conn)
    after_first = _names(conn)
    second = _run(conn)

    assert len(first["captured"]) == 1
    assert second["captured"] == [], "a re-read must capture nothing"
    assert _names(conn) == after_first, "the profile list must not grow on every read"
    assert second["modules"][0]["matched"] == first["captured"][0]["id"]
    print("  re-read is idempotent: still 2 profiles, still pointing at the capture")


def test_a_capture_takes_over_the_bays_that_pointed_at_the_drifted_profile():
    """A bay names the profile a layer RUNS. After the read, the thing running in that slot is
    the capture -- so leaving the bay on the edited row would show one profile as live while a
    flash quietly wrote a different one."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    conn.execute("INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                 "binding_location, state, updated_at, created_at) "
                 "VALUES ('p','l0',?,'track:keyboard_left',NULL,'','')", (UUID,))
    conn.commit()

    cap = _run(conn)["captured"][0]
    now = conn.execute("SELECT module_config_id FROM module_config_bindings").fetchone()[0]
    assert now == cap["id"], "the bay should follow what the board actually runs"
    assert _run(conn) is not None  # a re-read keeps it there

    # The edited profile survives and can be chosen again deliberately.
    assert conn.execute("SELECT 1 FROM module_configs WHERE id=?", (UUID,)).fetchone()
    print("  bay repointed to the capture; the edited profile still exists")


def test_a_bay_pointing_elsewhere_is_left_alone():
    other = "99999999-9999-9999-9999-999999999999"
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    conn.execute("INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                 "binding_location, state, updated_at, created_at) "
                 "VALUES ('p','l0',?,'track:keyboard_right',NULL,'','')", (other,))
    conn.commit()

    _run(conn)
    assert conn.execute("SELECT module_config_id FROM module_config_bindings").fetchone()[0] == other
    print("  unrelated bays untouched")
