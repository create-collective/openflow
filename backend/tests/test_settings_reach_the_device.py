"""A setting changed in the UI must be findable by the flash path.

THE BUG THIS PINS. `set_setting("tapping_term_ms", 250)` wrote
`settings.correlation_id = "tapping_term_ms"`, while `flash._read_term_flavour` looked up
`"8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05"`. They never met. So every device-scope setting in the
UI was inert: tapping term and flavour silently fell back to 200/0, and `_read_timeouts`
returned None, meaning SYS_SET_TIMEOUTS was never emitted at all. Seven settings were labelled
"Flashed to the device" and none of them were.

There was no test over db/settings.py at all, which is exactly why nobody noticed. This file is
that test, and it deliberately asserts against the FLASH side rather than against settings.py's
own round trip -- a test that only checked set_setting/get_settings would have passed happily
throughout the entire period the bug existed.

Note the bug had two halves. Matching the KEY is not sufficient: the UI stores "Balanced" while
FLAVOUR_ENUM wants "balanced", and led_action_override stores "until next layer change" where
the wire value is "until_layer_change". Both halves are covered below.
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

from openflow_backend.db import settings as st          # noqa: E402
from openflow_backend.device import flash as F          # noqa: E402


class KeepOpen:
    """`connect()` stand-in whose close() is a no-op, so the :memory: DB outlives the call."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE settings (
        id INTEGER PRIMARY KEY, value TEXT, correlation_id TEXT, type TEXT,
        created_at TEXT, updated_at TEXT)""")
    return conn


def _set(conn, key, value):
    with mock.patch.object(st, "connect", lambda: KeepOpen(conn)):
        return st.set_setting(key, value)


def _get(conn):
    with mock.patch.object(st, "connect", lambda: KeepOpen(conn)):
        return st.get_settings()


def _field(doc, fid):
    for g in doc["groups"]:
        for f in g["fields"]:
            if f["id"] == fid:
                return f
    raise AssertionError(f"no field {fid}")


def test_tapping_term_set_in_the_ui_is_what_the_flash_encodes():
    """The headline regression."""
    conn = _db()
    _set(conn, "tapping_term_ms", 250)
    term, _flavour = F._read_term_flavour(conn)
    assert term == 250, f"flash read {term}, not the 250 the user set"


def test_interrupt_flavor_needs_the_value_translated_too_not_just_the_key():
    """'Balanced' is not 'balanced'. Matching only the correlation id still yields flavour 0."""
    conn = _db()
    _set(conn, "interrupt_flavor", "Tap-Preferred")
    _term, flavour = F._read_term_flavour(conn)
    assert flavour == 2, (
        f"flash read flavour {flavour}; FLAVOUR_ENUM wants the wire value 'tap-preferred'")


def test_timeouts_are_emitted_at_all():
    """_read_timeouts returns None unless BOTH rows exist, and None means no SYS_SET_TIMEOUTS
    op is added to the plan -- the setting did nothing, silently."""
    conn = _db()
    assert F._read_timeouts(conn) is None, "fixture should start with no timeout rows"
    _set(conn, "idle_timeout_s", 120)
    _set(conn, "sleep_timeout_s", 600)
    got = F._read_timeouts(conn)
    assert got is not None, "no SYS_SET_TIMEOUTS would be emitted"
    assert got[0] == 120_000 and got[1] == 600_000, got


def test_the_value_survives_a_round_trip_to_the_ui():
    """Storing the wire value must not make the UI show something the user did not choose."""
    conn = _db()
    for fid, val in (("interrupt_flavor", "Hold-Preferred"),
                     ("led_action_override", "until next layer change"),
                     ("led_scan_mode", False),
                     ("tapping_term_ms", 321)):
        _set(conn, fid, val)
    doc = _get(conn)
    assert _field(doc, "interrupt_flavor")["value"] == "Hold-Preferred"
    assert _field(doc, "led_action_override")["value"] == "until next layer change"
    assert _field(doc, "led_scan_mode")["value"] is False
    assert _field(doc, "tapping_term_ms")["value"] == 321


def test_device_rows_are_keyed_by_the_nayaflow_uuid():
    """Sharing the correlation id is what lets an imported NayaFlow DB be read correctly."""
    conn = _db()
    _set(conn, "tapping_term_ms", 250)
    keys = {r["correlation_id"] for r in conn.execute("SELECT correlation_id FROM settings")}
    assert keys == {"8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05"}, keys


def test_a_nayaflow_database_is_read_without_importing_anything():
    """The reverse of the same bug: rows NayaFlow wrote must show up in our UI."""
    conn = _db()
    conn.execute("INSERT INTO settings (value, correlation_id, type) VALUES (?,?,?)",
                 ("450", "8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05", "slider"))
    conn.execute("INSERT INTO settings (value, correlation_id, type) VALUES (?,?,?)",
                 ("tap-unless-interrupted", "24de8555-1a56-4e02-a1c3-3641603a5ac9", "select"))
    doc = _get(conn)
    assert _field(doc, "tapping_term_ms")["value"] == 450
    assert _field(doc, "interrupt_flavor")["value"] == "Tap-Unless-Interrupted"


def test_app_settings_keep_their_readable_id():
    """Only device fields need the UUID; app-only rows nothing else reads stay legible."""
    conn = _db()
    _set(conn, "tray_battery", True)
    keys = {r["correlation_id"] for r in conn.execute("SELECT correlation_id FROM settings")}
    assert keys == {"tray_battery"}, keys


def test_legacy_rows_are_carried_over_not_dropped():
    """A user's existing choice is real intent; migration moves it AND translates the value."""
    conn = _db()
    conn.execute("INSERT INTO settings (value, correlation_id, type) VALUES (?,?,?)",
                 ("275", "tapping_term_ms", "slider"))
    conn.execute("INSERT INTO settings (value, correlation_id, type) VALUES (?,?,?)",
                 ("Tap-Preferred", "interrupt_flavor", "select"))
    st.migrate_legacy_setting_keys(conn)
    term, flavour = F._read_term_flavour(conn)
    assert term == 275, "the legacy tapping term was lost"
    assert flavour == 2, "the legacy flavour was moved but not translated to its wire value"
    left = {r["correlation_id"] for r in conn.execute("SELECT correlation_id FROM settings")}
    assert "tapping_term_ms" not in left, "the stale row should be gone, not shadowing the new one"


def test_migration_does_not_clobber_a_real_nayaflow_row():
    """A UUID row is more authoritative than a stale plain-id row."""
    conn = _db()
    conn.execute("INSERT INTO settings (value, correlation_id, type) VALUES (?,?,?)",
                 ("999", "tapping_term_ms", "slider"))
    conn.execute("INSERT INTO settings (value, correlation_id, type) VALUES (?,?,?)",
                 ("300", "8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05", "slider"))
    st.migrate_legacy_setting_keys(conn)
    term, _ = F._read_term_flavour(conn)
    assert term == 300, "the authoritative UUID row was overwritten by the stale one"


def test_every_field_declares_its_provenance():
    """The badge is the work queue; a field with no provenance is an unlabelled claim."""
    missing = [f["id"] for g in st.SETTINGS_SCHEMA for f in g["fields"] if "provenance" not in f]
    assert not missing, f"fields with no provenance: {missing}"


def test_nothing_claims_verified_without_a_device_key():
    """'verified' means the flash path can actually find it. No key, no claim."""
    bad = [f["id"] for g in st.SETTINGS_SCHEMA for f in g["fields"]
           if f.get("provenance") == st.VERIFIED and not f.get("device_key")]
    assert not bad, f"claimed verified with no correlation id: {bad}"
