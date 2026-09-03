"""A flash plan must be scoped to ONE profile, and must refuse to guess.

The layers table spans every profile. desired_from_db used to iterate all of them and let
d.layers[order] be overwritten, so with three profiles on the reference machine the plan held
whichever profile the query returned last -- i.e. flashing would have written an essentially
arbitrary keymap, and a different one as soon as the DB changed.

`state = 'ON_BOARD'` cannot be used to pick either: importing a device read sets it, so several
profiles claim it at once.
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


def _db(profiles):
    """profiles: {profile_id: {position: action_code}} -- one layer 0 each."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE profiles (id TEXT, name TEXT, order_id INT, state TEXT);
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
    for n, (pid, keys) in enumerate(profiles.items()):
        # every profile claims ON_BOARD, exactly as the real DB does after an import
        conn.execute("INSERT INTO profiles VALUES (?,?,?, 'ON_BOARD')", (pid, pid, n))
        lid = f"L-{pid}"
        conn.execute("INSERT INTO layers VALUES (?, 0, ?)", (lid, pid))
        for pos, code in keys.items():
            kid = f"K-{pid}-{pos}"
            conn.execute("INSERT INTO keys VALUES (?,?,?,NULL)", (kid, lid, pos))
            conn.execute("INSERT INTO key_bindings VALUES (?,?, 'tap', 'key', ?, NULL)",
                         (str(uuid.uuid4()), kid, code))
    conn.commit()
    return conn


def test_refuses_to_guess_between_profiles():
    conn = _db({"alpha": {0: "A"}, "beta": {0: "B"}, "gamma": {0: "C"}})
    try:
        F.desired_from_db(conn)
    except F.AmbiguousProfileError as e:
        assert "alpha" in str(e) and "beta" in str(e), "the error must name the candidates"
        print("  3 profiles -> refuses, and names them")
        return
    raise AssertionError("picked a profile silently -- this is the bug that would flash the wrong map")


def test_scopes_to_the_requested_profile():
    conn = _db({"alpha": {0: "A"}, "beta": {0: "B"}})
    for pid, want in (("alpha", "A"), ("beta", "B")):
        d = F.desired_from_db(conn, pid)
        assert d.profile_id == pid
        typ, param = d.layers[0][0]
        # 4-byte keypress param: [usage_lo][usage_hi][page][mods]
        from openflow_backend.device import keymap_read as kr
        assert kr.decode_keypress(param)[1] == want, f"{pid} produced the wrong key"
    print("  each profile produces its own keymap, no bleed between them")


def test_single_profile_needs_no_argument():
    d = F.desired_from_db(_db({"solo": {0: "A"}}))
    assert d.profile_id == "solo"
    print("  one profile -> used without being asked for")


def test_unknown_profile_is_rejected():
    try:
        F.desired_from_db(_db({"alpha": {0: "A"}}), "does-not-exist")
    except ValueError:
        print("  an unknown profile id is rejected")
        return
    raise AssertionError("accepted a profile id that does not exist")


if __name__ == "__main__":
    for fn in (test_refuses_to_guess_between_profiles,
               test_scopes_to_the_requested_profile,
               test_single_profile_needs_no_argument,
               test_unknown_profile_is_rejected):
        print(fn.__name__)
        fn()
    print("\nOK")
