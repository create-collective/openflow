"""What we last saw on the keyboard, persisted so it survives a page reload.

This used to live only in the browser, deliberately: surviving a reload would mean claiming
knowledge of a keyboard we had not talked to since. That reasoning was right about the risk and
wrong about the remedy. Dropping the state made the live tags and blue dots vanish on every
refresh, which looked like a bug twice in one session and sent us debugging a read path that
was working fine.

The honest fix is not to forget, but to say WHEN. State is stored with the time it was taken
and what produced it, and the UI shows "as of HH:MM" rather than presenting it as current
truth. A flash clears it rather than updating it -- we have just changed the device, and the
next read is the only thing that can say what it now holds.

It lives in `settings`, the key/value table NayaFlow already uses, so no new table and no
migration.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .database import connect

KEY = "openflow.device_state"
# Half status -- firmware, battery, what is docked. A different read from the module configs,
# and one Device Manager used to fire on every single mount, so navigating away and back
# re-opened the port to ask the same questions.
KEY_STATUS = "openflow.device_status"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _write(conn, payload: dict, key: str = KEY) -> None:
    now = _now()
    blob = json.dumps(payload)
    if conn.execute("SELECT 1 FROM settings WHERE correlation_id=?", (key,)).fetchone():
        conn.execute("UPDATE settings SET value=?, updated_at=? WHERE correlation_id=?",
                     (blob, now, key))
    else:
        conn.execute("INSERT INTO settings (value, correlation_id, type, created_at, updated_at) "
                     "VALUES (?,?,?,?,?)", (blob, key, "json", now, now))


def _read(conn, key: str) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE correlation_id=?", (key,)).fetchone()
    if row is None or not row["value"]:
        return {}
    try:
        got = json.loads(row["value"])
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def save(modules: list, source: str = "read") -> dict:
    """Record a device read. `modules` is the /rpc/read-modules entry list."""
    payload = {"modules": modules, "at": _now(), "source": source}
    conn = connect()
    try:
        _write(conn, payload)
        conn.commit()
        return payload
    finally:
        conn.close()


def clear(reason: str = "flash") -> dict:
    """Forget what the board holds. Called after a write: whatever we believed is now stale,
    and only a read can replace it."""
    payload = {"modules": None, "at": _now(), "source": reason}
    conn = connect()
    try:
        _write(conn, payload)
        conn.commit()
        return payload
    finally:
        conn.close()


def load() -> dict:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE correlation_id=?", (KEY,)).fetchone()
        if row is None or not row["value"]:
            return {"modules": None, "at": None, "source": None}
        try:
            got = json.loads(row["value"])
        except (TypeError, ValueError):
            return {"modules": None, "at": None, "source": None}
        # Never hand back something shaped differently from what save() writes -- the UI keys
        # a lookup off it and a half-written blob would surface as a blank page, not an error.
        if not isinstance(got, dict):
            return {"modules": None, "at": None, "source": None}
        mods = got.get("modules")
        return {"modules": mods if isinstance(mods, list) else None,
                "at": got.get("at"), "source": got.get("source")}
    finally:
        conn.close()


def save_status(halves: list) -> dict:
    """Record the half status Device Manager shows, so the page can paint from cache."""
    payload = {"halves": halves, "at": _now()}
    conn = connect()
    try:
        _write(conn, payload, KEY_STATUS)
        conn.commit()
        return payload
    finally:
        conn.close()


def load_status() -> dict:
    conn = connect()
    try:
        got = _read(conn, KEY_STATUS)
        halves = got.get("halves")
        return {"halves": halves if isinstance(halves, list) else None, "at": got.get("at")}
    finally:
        conn.close()
