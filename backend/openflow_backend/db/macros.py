"""Macro editor persistence.

NayaFlow never shipped a macro editor, but its schema is ready for one (a `macros`
row + typed step tables) and ZMK supports macros natively. We implement the common
step kinds now: key actions (press/release/tap), text, and wait-for-release. Mouse
and loop steps have tables too and can be added later.

Steps are merged across the typed tables and ordered by order_id so the editor
sees one flat list.
"""

from __future__ import annotations

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
        for tbl in ("standard_action_macro_steps", "text_action_macro_steps",
                    "wait_for_release_macro_steps", "mouse_action_macro_steps",
                    "loop_action_macro_steps"):
            conn.execute(f"DELETE FROM {tbl} WHERE macro_id=?", (macro_id,))
        conn.execute("DELETE FROM macros WHERE id=?", (macro_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def add_step(macro_id: str, kind: str, *, action_code: str | None = None,
             state: str = "tap", input: str = "", delay: int = 30) -> dict:
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
        else:
            raise ValueError(f"unknown step kind: {kind}")
        conn.commit()
        return {"ok": True, "id": sid}
    finally:
        conn.close()


_STEP_TABLES = (
    "standard_action_macro_steps", "text_action_macro_steps",
    "wait_for_release_macro_steps", "mouse_action_macro_steps",
    "loop_action_macro_steps",
)


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
