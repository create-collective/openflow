"""A read binds a layer's bays to the profile the slot actually MATCHES, capture included.

The bay bytes on the keyboard name slots; the import turns them into profiles. It used to do
that by the slot's uuid alone and before the read had captured anything, so a slot the app knew
only by content -- every NayaFlow-written slot, and any slot the read was about to capture --
was dropped: layer 0 came back with no Touch profile, and the next flash preview offered to
delete the slot (SCRUM-61, 2026-09-16). Now the slot is resolved first and the bay binds to the
matched config. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest                        # noqa: E402
from openflow_backend.db import keymap_import as ki          # noqa: E402
from openflow_backend.db import module_profiles as mp        # noqa: E402
import test_module_capture as mc                             # noqa: E402
from test_import_identity import _read as _keymap_read       # noqa: E402

SLOT = 1          # the Track slot in test_module_capture's module read
BAY = "track:keyboard_left"


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


def _conn(app_bindings):
    """test_module_capture's module tables plus the keymap tables the import writes."""
    conn = mc._db(app_bindings)
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, order_id INT, state TEXT, icon_id TEXT,
                               author_name TEXT, description TEXT, id TEXT,
                               updated_at TEXT, created_at TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, profile_id TEXT, id TEXT,
                             updated_at TEXT, created_at TEXT);
        CREATE TABLE keys (color_hex TEXT, position_id INT, layer_id TEXT, id TEXT,
                           updated_at TEXT, created_at TEXT);
        CREATE TABLE key_bindings (context TEXT, action_code TEXT, action_type TEXT,
                                   behavior TEXT, key_id TEXT, id TEXT,
                                   updated_at TEXT, created_at TEXT);
    """)
    return conn


def _read_keyboard_like_the_route(conn):
    """The route's order: resolve and capture the module slots, THEN import the keymap with a
    slot -> matched-config map. Mirrors rest.read_keyboard without a device."""
    mod_read = mc._read()
    keymap = _keymap_read()
    keymap["bays"] = {0: {BAY: SLOT}, 1: {BAY: "transparent"}}
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(conn)), \
         mock.patch.object(ki, "connect", lambda: KeepOpen(conn)):
        diff = rest._module_diff(mod_read, None)
        slot_cfg = rest._slot_config_map(diff["modules"], mod_read["by_uuid"])
        out = ki.import_read(keymap, "first", slot_cfg)
        moved = mp.repoint_bays([(e.get("uuid"), e.get("matched")) for e in diff["modules"]],
                                out["profileId"])
    return diff, slot_cfg, out, moved


def _bay(conn, profile_id):
    row = conn.execute(
        "SELECT b.module_config_id AS cfg, b.state AS state FROM module_config_bindings b "
        "JOIN layers l ON l.id = b.layer_id WHERE b.profile_id=? AND l.order_id=0 "
        "AND b.binding_location=?", (profile_id, BAY)).fetchone()
    return (row["cfg"], row["state"]) if row else None


def test_a_slot_the_app_matches_by_content_binds_the_bay_to_that_profile():
    conn = _conn(dict(mc._DEVICE))                       # app == board: matched by content
    diff, slot_cfg, out, moved = _read_keyboard_like_the_route(conn)
    assert diff["captured"] == []
    assert slot_cfg == {SLOT: mc.UUID}
    assert _bay(conn, out["profileId"]) == (mc.UUID, None)
    assert moved == 0, "nothing to repoint: the import already bound the right profile"
    print("  a matching slot: the bay binds to the live profile")


def test_a_slot_the_read_captures_binds_the_bay_to_the_capture():
    """The failing case of 2026-09-16: the app's copy had drifted, the read captured the board's
    state as a new profile, and layer 0's bay came back EMPTY because the import had already
    run against the slot's uuid alone."""
    drifted = dict(mc._DEVICE, **{"tap:track:button_1": "M2"})
    conn = _conn(drifted)
    diff, slot_cfg, out, moved = _read_keyboard_like_the_route(conn)
    assert len(diff["captured"]) == 1
    cap = diff["captured"][0]["id"]
    assert slot_cfg == {SLOT: cap}, "the map names the capture, not the drifted uuid"
    assert _bay(conn, out["profileId"]) == (cap, None), "layer 0 must bind to the capture"
    print("  a captured slot: the bay binds to the capture, not to nothing")


def test_slot_map_falls_back_to_the_uuid_for_a_slot_with_no_match():
    entries = [{"uuid": "u-1", "matched": None}, {"uuid": "u-2", "matched": "cfg-2"}]
    assert rest._slot_config_map(entries, {"u-1": 3, "u-2": 4}) == {3: "u-1", 4: "cfg-2"}
    assert rest._slot_config_map(entries, None) == {}
    print("  unmatched slots keep their uuid; unknown uuids are ignored")
