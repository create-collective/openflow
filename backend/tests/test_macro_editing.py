"""Renaming a macro, and editing a step in place.

Neither existed: a macro's name was fixed at creation, and a step's delay could only be chosen
at the moment it was added -- so correcting a timing meant deleting the step and rebuilding it,
which also lost its position in the sequence.

Context worth keeping attached to this file: macros do NOT reach the keyboard. The firmware
reserves the macro behaviour type (0x02) but implements no macro table -- READ_MACRO_LIST
answers and stays empty, and seven encoding variants of WRITE_MACRO_LIST / WRITE_MACRO_DATA were
all ACKed and discarded (docs/module-field-map.md, C9/C10). NayaCore never sends those opcodes
either. So this is a local editor by necessity, and the palette shows macros as unbindable.
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

from openflow_backend.db import macros as mac    # noqa: E402


class KeepOpen:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE macros (
        id TEXT PRIMARY KEY, name TEXT, type TEXT, icon_id TEXT, order_id INTEGER,
        duration INTEGER, size INTEGER, author_name TEXT, description TEXT,
        created_at TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE standard_action_macro_steps (
        id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT, order_id INTEGER,
        delay INTEGER, macro_id TEXT, action_code TEXT, state TEXT)""")
    conn.execute("""CREATE TABLE text_action_macro_steps (
        id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT, order_id INTEGER,
        delay INTEGER, macro_id TEXT, input TEXT)""")
    conn.execute("""CREATE TABLE wait_for_release_macro_steps (
        id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT, order_id INTEGER,
        delay INTEGER, macro_id TEXT)""")
    for extra in ("mouse_action_macro_steps", "loop_action_macro_steps"):
        conn.execute(f"""CREATE TABLE {extra} (
            id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT, order_id INTEGER,
            delay INTEGER, macro_id TEXT)""")
    conn.execute("""CREATE TABLE launch_action_macro_steps (
        id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT, order_id INTEGER,
        delay INTEGER, macro_id TEXT, program TEXT, args TEXT, shell INTEGER DEFAULT 0)""")
    return conn


def _patched(conn):
    return mock.patch.object(mac, "connect", lambda: KeepOpen(conn))


def _macro_with_steps(conn):
    with _patched(conn):
        m = mac.create_macro("test")
        a = mac.add_step(m["id"], "key", action_code="B", state="tap", delay=30)
        b = mac.add_step(m["id"], "text", input="hi", delay=40)
        c = mac.add_step(m["id"], "wait", delay=50)
    return m["id"], a["id"], b["id"], c["id"]


def _steps(conn, mid):
    with _patched(conn):
        doc = mac.get_macros()
    return next(m for m in doc["macros"] if m["id"] == mid)["steps"]


def test_rename():
    conn = _db()
    mid, *_ = _macro_with_steps(conn)
    with _patched(conn):
        mac.rename_macro(mid, "renamed")
        doc = mac.get_macros()
    assert doc["macros"][0]["name"] == "renamed"


def test_rename_refuses_an_empty_name():
    conn = _db()
    mid, *_ = _macro_with_steps(conn)
    for bad in ("", "   "):
        with _patched(conn):
            try:
                mac.rename_macro(mid, bad)
            except ValueError:
                continue
        raise AssertionError(f"accepted {bad!r} as a name")


def test_rename_unknown_macro_raises():
    conn = _db()
    with _patched(conn):
        try:
            mac.rename_macro("nope", "x")
        except ValueError:
            return
    raise AssertionError("renaming a macro that does not exist should raise")


def test_delay_can_be_changed_on_each_step_kind():
    """The point of the feature: all three kinds live in different tables."""
    conn = _db()
    mid, key_id, text_id, wait_id = _macro_with_steps(conn)
    with _patched(conn):
        for sid, ms in ((key_id, 111), (text_id, 222), (wait_id, 333)):
            mac.update_step(sid, delay=ms)
    got = {s["id"]: s["delay"] for s in _steps(conn, mid)}
    assert got[key_id] == 111 and got[text_id] == 222 and got[wait_id] == 333, got


def test_editing_a_step_does_not_move_it():
    """Delete-and-recreate was the old workaround and it sent the step to the end."""
    conn = _db()
    mid, key_id, _text, _wait = _macro_with_steps(conn)
    with _patched(conn):
        mac.update_step(key_id, delay=999)
    assert [s["id"] for s in _steps(conn, mid)][0] == key_id, "the edited step changed position"


def test_a_key_step_can_be_repointed():
    conn = _db()
    mid, key_id, *_ = _macro_with_steps(conn)
    with _patched(conn):
        mac.update_step(key_id, action_code="LCTRL + C", state="press")
    s = next(x for x in _steps(conn, mid) if x["id"] == key_id)
    assert s["actionCode"] == "LCTRL + C" and s["state"] == "press", s


def test_a_column_the_table_does_not_have_is_ignored_not_fatal():
    """The UI sends whatever the step kind implies; a wait step has no action_code."""
    conn = _db()
    mid, _k, _t, wait_id = _macro_with_steps(conn)
    with _patched(conn):
        r = mac.update_step(wait_id, delay=77, action_code="A")
    assert r["changed"] == ["delay"], r
    assert next(x for x in _steps(conn, mid) if x["id"] == wait_id)["delay"] == 77


def test_updating_nothing_is_a_no_op_not_an_error():
    conn = _db()
    _mid, key_id, *_ = _macro_with_steps(conn)
    with _patched(conn):
        assert mac.update_step(key_id)["changed"] == []


def test_unknown_step_raises():
    conn = _db()
    _macro_with_steps(conn)
    with _patched(conn):
        try:
            mac.update_step("nope", delay=1)
        except ValueError:
            return
    raise AssertionError("editing a step that does not exist should raise")


# --- launch / command steps ------------------------------------------------------------------
# These exist because a macro is executed HOST-side (the keyboard has no macro table), so
# "start a program" is a thing the runner can actually do. Their shape matches Create
# Companion's Action enum so an exported macro needs no translation.


def test_a_launch_step_keeps_its_args_as_a_list():
    """argv, not a string. A program path with a space must not become two arguments, and a
    metacharacter in an argument must not be able to start a second command."""
    conn = _db()
    with _patched(conn):
        m = mac.create_macro("run")
        mac.add_step(m["id"], "launch", program="C:/Program Files/app.exe",
                     args=["--flag", "a b", "x;y"], delay=10)
    s = _steps(conn, m["id"])[0]
    assert s["kind"] == "launch" and s["shell"] is False, s
    assert s["program"] == "C:/Program Files/app.exe"
    assert s["args"] == ["--flag", "a b", "x;y"], s["args"]


def test_a_command_step_is_marked_as_shell():
    conn = _db()
    with _patched(conn):
        m = mac.create_macro("run")
        mac.add_step(m["id"], "command", program="git status | head", delay=0)
    s = _steps(conn, m["id"])[0]
    assert s["kind"] == "command" and s["shell"] is True, s
    assert s["args"] == [], "a shell command has no argv of its own"


def test_launch_requires_a_program():
    conn = _db()
    with _patched(conn):
        m = mac.create_macro("run")
        for bad in ("", "   "):
            try:
                mac.add_step(m["id"], "launch", program=bad)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad!r} as a program")


def test_launch_steps_order_alongside_the_others():
    """One flat list: a launch step must interleave with keys, not sort to the end."""
    conn = _db()
    with _patched(conn):
        m = mac.create_macro("mixed")
        mac.add_step(m["id"], "key", action_code="A")
        mac.add_step(m["id"], "launch", program="app.exe")
        mac.add_step(m["id"], "text", input="hi")
    assert [s["kind"] for s in _steps(conn, m["id"])] == ["key", "launch", "text"]


def test_deleting_a_macro_takes_its_launch_steps_with_it():
    """delete_macro had its own hardcoded table list, which would have orphaned these."""
    conn = _db()
    with _patched(conn):
        m = mac.create_macro("run")
        mac.add_step(m["id"], "launch", program="app.exe")
        mac.delete_macro(m["id"])
    left = conn.execute("SELECT COUNT(*) c FROM launch_action_macro_steps").fetchone()["c"]
    assert left == 0, f"{left} orphaned launch step(s)"


def test_a_launch_step_can_be_repointed():
    conn = _db()
    with _patched(conn):
        m = mac.create_macro("run")
        sid = mac.add_step(m["id"], "launch", program="old.exe")["id"]
        mac.update_step(sid, program="new.exe", delay=5)
    s = _steps(conn, m["id"])[0]
    assert s["program"] == "new.exe" and s["delay"] == 5, s
