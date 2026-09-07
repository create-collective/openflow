"""Macro editor persistence.

WHERE MACROS RUN. Not on the keyboard. The firmware reserves the macro behaviour type (0x02)
but implements no macro table: READ_MACRO_LIST answers and stays empty, and seven encoding
variants of WRITE_MACRO_LIST / WRITE_MACRO_DATA were all acknowledged and discarded
(docs/module-field-map.md, C9/C10). NayaCore never sends those opcodes either. So a macro is
authored here and executed by a HOST-side engine -- Create Companion, which already runs
per-app actions off the F13-F24 transport keys.

That is why launch/command steps belong here at all: a keyboard could never start a program,
but the engine that will run these can. Their shape deliberately matches Companion's
`Action` enum (`{type: launch, program, args}` / `{type: command, command}`) so an exported
macro needs no translation.

Step kinds: key (press/release/tap), text, wait-for-release, launch, command. NayaFlow's schema
supplies the first three tables; `launch_action_macro_steps` is ours (see db/database.py
_ADDED_TABLES). Its mouse and loop tables exist and are carried for delete/reorder but cannot
be created yet.

Steps are merged across the typed tables and ordered by order_id so the editor sees one flat
list.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .database import connect


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _uid() -> str:
    return str(uuid.uuid4())


def get_macros() -> dict:
    conn = connect()
    try:
        out = []
        for m in conn.execute(
            "SELECT id, name, type, icon_id, order_id, description FROM macros ORDER BY order_id, name"
        ):
            steps = _steps_for(conn, m["id"])
            out.append({
                "id": m["id"], "name": m["name"], "type": m["type"],
                "orderId": m["order_id"], "description": m["description"],
                "steps": steps,
            })
        return {"macros": out}
    finally:
        conn.close()


def _steps_for(conn, macro_id: str) -> list[dict]:
    steps = []
    for r in conn.execute(
        "SELECT id, order_id, delay, action_code, state FROM standard_action_macro_steps WHERE macro_id=?",
        (macro_id,),
    ):
        steps.append({"id": r["id"], "kind": "key", "orderId": r["order_id"],
                      "delay": r["delay"], "actionCode": r["action_code"], "state": r["state"]})
    for r in conn.execute(
        "SELECT id, order_id, delay, input FROM text_action_macro_steps WHERE macro_id=?",
        (macro_id,),
    ):
        steps.append({"id": r["id"], "kind": "text", "orderId": r["order_id"],
                      "delay": r["delay"], "input": r["input"]})
    for r in conn.execute(
        "SELECT id, order_id, delay FROM wait_for_release_macro_steps WHERE macro_id=?",
        (macro_id,),
    ):
        steps.append({"id": r["id"], "kind": "wait", "orderId": r["order_id"], "delay": r["delay"]})
    # Launch/run. Reported with Create Companion's own shape -- {type: launch, program, args}
    # or {type: command, command} -- so an exported macro can be handed straight to the engine
    # that will actually run it. Nothing in OpenFlow executes these; see the module docstring.
    for r in conn.execute(
        "SELECT id, order_id, delay, program, args, shell FROM launch_action_macro_steps "
        "WHERE macro_id=?", (macro_id,),
    ):
        try:
            args = json.loads(r["args"] or "[]")
        except ValueError:
            args = []
        steps.append({"id": r["id"], "kind": "command" if r["shell"] else "launch",
                      "orderId": r["order_id"], "delay": r["delay"],
                      "program": r["program"] or "", "args": args,
                      "shell": bool(r["shell"])})
    steps.sort(key=lambda s: s["orderId"])
    return steps


def create_macro(name: str) -> dict:
    conn = connect()
    try:
        now = _now()
        mid = _uid()
        max_order = conn.execute("SELECT COALESCE(MAX(order_id), -1) FROM macros").fetchone()[0]
        conn.execute(
            "INSERT INTO macros (name, type, order_id, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name, "standard", max_order + 1, mid, now, now),
        )
        conn.commit()
        return {"ok": True, "id": mid, "name": name}
    finally:
        conn.close()


def delete_macro(macro_id: str) -> dict:
    conn = connect()
    try:
        # _STEP_TABLES, not a second hardcoded list -- this one had already fallen behind by
        # one table, which would have orphaned every launch step when its macro was deleted.
        for tbl in _STEP_TABLES:
            conn.execute(f"DELETE FROM {tbl} WHERE macro_id=?", (macro_id,))
        conn.execute("DELETE FROM macros WHERE id=?", (macro_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def add_step(macro_id: str, kind: str, *, action_code: str | None = None,
             state: str = "tap", input: str = "", delay: int = 30,
             program: str = "", args: list | None = None) -> dict:
    conn = connect()
    try:
        now = _now()
        sid = _uid()
        # Next order_id across all step tables for this macro.
        order = len(_steps_for(conn, macro_id))
        if kind == "key":
            conn.execute(
                "INSERT INTO standard_action_macro_steps "
                "(id, updated_at, created_at, order_id, delay, macro_id, action_code, state) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (sid, now, now, order, delay, macro_id, action_code or "", state),
            )
        elif kind == "text":
            conn.execute(
                "INSERT INTO text_action_macro_steps "
                "(id, updated_at, created_at, order_id, delay, macro_id, input) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, now, now, order, delay, macro_id, input),
            )
        elif kind == "wait":
            conn.execute(
                "INSERT INTO wait_for_release_macro_steps "
                "(id, updated_at, created_at, order_id, delay, macro_id) "
                "VALUES (?,?,?,?,?,?)",
                (sid, now, now, order, delay, macro_id),
            )
        elif kind in ("launch", "command"):
            if not (program or "").strip():
                raise ValueError("a launch step needs a program")
            conn.execute(
                "INSERT INTO launch_action_macro_steps "
                "(id, updated_at, created_at, order_id, delay, macro_id, program, args, shell) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, now, now, order, delay, macro_id, program.strip(),
                 json.dumps(list(args or []) if kind == "launch" else []),
                 1 if kind == "command" else 0),
            )
        else:
            raise ValueError(f"unknown step kind: {kind}")
        conn.commit()
        return {"ok": True, "id": sid}
    finally:
        conn.close()


_STEP_TABLES = (
    "standard_action_macro_steps", "text_action_macro_steps",
    "wait_for_release_macro_steps", "mouse_action_macro_steps",
    "loop_action_macro_steps", "launch_action_macro_steps",
)


def rename_macro(macro_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("a macro needs a name")
    conn = connect()
    try:
        cur = conn.execute("UPDATE macros SET name=?, updated_at=? WHERE id=?",
                           (name, _now(), macro_id))
        if cur.rowcount == 0:
            raise ValueError(f"no macro {macro_id}")
        conn.commit()
        return {"ok": True, "id": macro_id, "name": name}
    finally:
        conn.close()


def update_step(step_id: str, *, delay: int | None = None, action_code: str | None = None,
                state: str | None = None, input: str | None = None,
                program: str | None = None) -> dict:
    """Edit a step in place.

    Delay was settable only at the moment a step was added, so fixing a timing meant deleting
    the step and rebuilding it -- which also lost its position. The step's table is found by
    id rather than passed in, because the caller has a step id and nothing else; which of the
    five tables holds it is our problem, not theirs.

    Only columns that exist on the found table are written, so asking to change `input` on a
    key step is ignored rather than raising -- the UI sends whatever the step kind implies.
    """
    fields = {"delay": delay, "action_code": action_code, "state": state,
              "input": input, "program": program}
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return {"ok": True, "id": step_id, "changed": []}
    conn = connect()
    try:
        for tbl in _STEP_TABLES:
            row = conn.execute(f"SELECT id FROM {tbl} WHERE id=?", (step_id,)).fetchone()
            if row is None:
                continue
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})")}
            usable = {k: v for k, v in fields.items() if k in cols}
            if usable:
                sets = ", ".join(f"{k}=?" for k in usable)
                conn.execute(f"UPDATE {tbl} SET {sets}, updated_at=? WHERE id=?",
                             (*usable.values(), _now(), step_id))
                conn.commit()
            return {"ok": True, "id": step_id, "changed": sorted(usable)}
        raise ValueError(f"no step {step_id}")
    finally:
        conn.close()


def _macro_id_for_step(conn, step_id: str) -> str | None:
    for tbl in _STEP_TABLES:
        r = conn.execute(f"SELECT macro_id FROM {tbl} WHERE id=?", (step_id,)).fetchone()
        if r:
            return r["macro_id"]
    return None


def _reindex(conn, macro_id: str) -> None:
    """Renumber a macro's steps 0..n-1 by current order across all step tables."""
    steps = _steps_for(conn, macro_id)  # sorted by order_id
    for new_order, s in enumerate(steps):
        if s["orderId"] != new_order:
            for tbl in _STEP_TABLES:
                conn.execute(f"UPDATE {tbl} SET order_id=? WHERE id=?", (new_order, s["id"]))


def delete_step(step_id: str) -> dict:
    conn = connect()
    try:
        macro_id = _macro_id_for_step(conn, step_id)
        for tbl in _STEP_TABLES:
            conn.execute(f"DELETE FROM {tbl} WHERE id=?", (step_id,))
        if macro_id:
            _reindex(conn, macro_id)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def reorder_steps(macro_id: str, ordered_ids: list[str]) -> dict:
    """Set step order to match ordered_ids (for drag-to-reorder)."""
    conn = connect()
    try:
        for new_order, sid in enumerate(ordered_ids):
            for tbl in _STEP_TABLES:
                conn.execute(f"UPDATE {tbl} SET order_id=? WHERE id=? AND macro_id=?",
                             (new_order, sid, macro_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
