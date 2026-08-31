"""Profile management + portable import/export.

A profile owns an ordered set of layers (each with 97 keys + bindings). Profiles
are switchable, renameable, duplicable, and can be exported to / imported from a
self-contained JSON backup — the cross-keyboard workflow (back up one board, load
onto another). Import/duplicate remap all internal id references:
  - layer-switch action codes (MO_LAYER_/TO_LAYER_/TOGGLE_LAYER_/STICKY_LAYER_ + id)
  - macro references (action_type 'macro', action_code = macro id)
so the copy is fully self-consistent with fresh ids.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .database import connect

EXPORT_VERSION = 1
UNSET_COLOR = "#xxxxxx"
LAYER_PREFIXES = ("MO_LAYER_", "TO_LAYER_", "TOGGLE_LAYER_", "STICKY_LAYER_")
KEYS_PER_LAYER = 97


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _uid() -> str:
    return str(uuid.uuid4())


def _remap_code(code, action_type, layer_map, macro_map):
    """Rewrite a binding's action_code for a copied profile."""
    if not code:
        return code
    for p in LAYER_PREFIXES:
        if code.startswith(p):
            old = code[len(p):]
            return p + layer_map.get(old, old)
    if action_type == "macro":
        return macro_map.get(code, code)
    return code


# --- basic CRUD -----------------------------------------------------------

def list_profiles() -> list[dict]:
    conn = connect()
    try:
        return [
            {"id": r["id"], "name": r["name"], "state": r["state"], "orderId": r["order_id"]}
            for r in conn.execute("SELECT id, name, state, order_id FROM profiles ORDER BY order_id")
        ]
    finally:
        conn.close()


def create_profile(name: str) -> dict:
    """New profile with one empty 'Base' layer (97 keys)."""
    conn = connect()
    try:
        now = _now()
        pid = _uid()
        max_order = conn.execute("SELECT COALESCE(MAX(order_id), -1) FROM profiles").fetchone()[0]
        conn.execute(
            "INSERT INTO profiles (name, order_id, state, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name, max_order + 1, "FLOW", pid, now, now),
        )
        _new_layer(conn, pid, "Base", 0, now)
        conn.commit()
        return {"ok": True, "id": pid, "name": name}
    finally:
        conn.close()


def _new_layer(conn, profile_id, name, order_id, now, icon_id=None, animation_id=None) -> str:
    lid = _uid()
    conn.execute(
        "INSERT INTO layers (name, order_id, icon_id, profile_id, animation_id, id, updated_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (name, order_id, icon_id, profile_id, animation_id, lid, now, now),
    )
    for pos in range(KEYS_PER_LAYER):
        conn.execute(
            "INSERT INTO keys (color_hex, position_id, layer_id, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (UNSET_COLOR, pos, lid, _uid(), now, now),
        )
    return lid


def rename_profile(profile_id: str, name: str) -> dict:
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE profiles SET name=?, updated_at=? WHERE id=?", (name, _now(), profile_id)
        )
        if cur.rowcount == 0:
            raise ValueError(f"no profile {profile_id}")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def delete_profile(profile_id: str) -> dict:
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if n <= 1:
            raise ValueError("cannot delete the only profile")
        _delete_profile_rows(conn, profile_id)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def _delete_profile_rows(conn, profile_id):
    layer_ids = [r["id"] for r in conn.execute("SELECT id FROM layers WHERE profile_id=?", (profile_id,))]
    for lid in layer_ids:
        key_ids = [r["id"] for r in conn.execute("SELECT id FROM keys WHERE layer_id=?", (lid,))]
        for kid in key_ids:
            conn.execute("DELETE FROM key_bindings WHERE key_id=?", (kid,))
        conn.execute("DELETE FROM keys WHERE layer_id=?", (lid,))
    conn.execute("DELETE FROM layers WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM module_config_bindings WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))


# --- export ---------------------------------------------------------------

def _profile_payload(conn, profile_id: str) -> dict:
    """Self-contained profile: layers + keys + bindings + referenced macros."""
    p = conn.execute("SELECT name, icon_id FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if p is None:
        raise ValueError(f"no profile {profile_id}")
    layers = []
    macro_ids: set[str] = set()
    for l in conn.execute(
        "SELECT id, name, order_id, icon_id, animation_id FROM layers WHERE profile_id=? ORDER BY order_id",
        (profile_id,),
    ):
        layers.append(_layer_payload(conn, l, macro_ids))
    return {
        "version": EXPORT_VERSION,
        "kind": "profile",
        "profile": {"name": p["name"], "iconId": p["icon_id"]},
        "layers": layers,
        "macros": _macros_payload(conn, macro_ids),
    }


def _layer_payload(conn, layer_row, macro_ids: set) -> dict:
    keys = []
    for k in conn.execute(
        "SELECT id, position_id, color_hex FROM keys WHERE layer_id=? ORDER BY position_id",
        (layer_row["id"],),
    ):
        bindings = []
        for b in conn.execute(
            "SELECT behavior, action_type, action_code, context FROM key_bindings WHERE key_id=?",
            (k["id"],),
        ):
            if b["action_type"] == "macro" and b["action_code"]:
                macro_ids.add(b["action_code"])
            bindings.append({
                "behavior": b["behavior"], "actionType": b["action_type"],
                "actionCode": b["action_code"], "context": b["context"],
            })
        keys.append({"positionId": k["position_id"], "colorHex": k["color_hex"], "bindings": bindings})
    # capture the source layer id so layer-switch refs can be remapped on import
    return {
        "srcId": layer_row["id"], "name": layer_row["name"], "orderId": layer_row["order_id"],
        "iconId": layer_row["icon_id"], "animationId": layer_row["animation_id"], "keys": keys,
    }


def _macros_payload(conn, macro_ids: set) -> list[dict]:
    out = []
    for mid in macro_ids:
        m = conn.execute("SELECT id, name, type, icon_id FROM macros WHERE id=?", (mid,)).fetchone()
        if m is None:
            continue
        steps = []
        for tbl, extra in (
            ("standard_action_macro_steps", "action_code, state"),
            ("text_action_macro_steps", "input"),
            ("wait_for_release_macro_steps", "delay AS _d2"),
        ):
            for r in conn.execute(
                f"SELECT id, order_id, delay, {extra} FROM {tbl} WHERE macro_id=?", (mid,)
            ):
                d = dict(r)
                d["_table"] = tbl
                steps.append(d)
        out.append({"srcId": m["id"], "name": m["name"], "type": m["type"], "iconId": m["icon_id"], "steps": steps})
    return out


def export_profile(profile_id: str) -> dict:
    conn = connect()
    try:
        return _profile_payload(conn, profile_id)
    finally:
        conn.close()


def export_layer(layer_id: str) -> dict:
    conn = connect()
    try:
        l = conn.execute(
            "SELECT id, name, order_id, icon_id, animation_id FROM layers WHERE id=?", (layer_id,)
        ).fetchone()
        if l is None:
            raise ValueError(f"no layer {layer_id}")
        macro_ids: set[str] = set()
        payload = _layer_payload(conn, l, macro_ids)
        return {
            "version": EXPORT_VERSION, "kind": "layer",
            "layer": payload, "macros": _macros_payload(conn, macro_ids),
        }
    finally:
        conn.close()


# --- import / duplicate ---------------------------------------------------

def _create_macros(conn, macros, now) -> dict:
    """Create macros from a payload, return src->new id map."""
    macro_map = {}
    for m in macros:
        new_mid = _uid()
        macro_map[m["srcId"]] = new_mid
        max_order = conn.execute("SELECT COALESCE(MAX(order_id), -1) FROM macros").fetchone()[0]
        conn.execute(
            "INSERT INTO macros (name, type, icon_id, order_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?)",
            (m["name"], m.get("type") or "standard", m.get("iconId"), max_order + 1, new_mid, now, now),
        )
        for s in m.get("steps", []):
            tbl = s["_table"]
            if tbl == "standard_action_macro_steps":
                conn.execute(
                    "INSERT INTO standard_action_macro_steps (id, updated_at, created_at, order_id, delay, macro_id, action_code, state) VALUES (?,?,?,?,?,?,?,?)",
                    (_uid(), now, now, s["order_id"], s.get("delay", 30), new_mid, s.get("action_code", ""), s.get("state", "tap")),
                )
            elif tbl == "text_action_macro_steps":
                conn.execute(
                    "INSERT INTO text_action_macro_steps (id, updated_at, created_at, order_id, delay, macro_id, input) VALUES (?,?,?,?,?,?,?)",
                    (_uid(), now, now, s["order_id"], s.get("delay", 30), new_mid, s.get("input", "")),
                )
            elif tbl == "wait_for_release_macro_steps":
                conn.execute(
                    "INSERT INTO wait_for_release_macro_steps (id, updated_at, created_at, order_id, delay, macro_id) VALUES (?,?,?,?,?,?)",
                    (_uid(), now, now, s["order_id"], s.get("delay", 30), new_mid),
                )
    return macro_map


def _import_layers(conn, profile_id, layers, now, macro_map, base_order=0):
    """Two-pass: create layers (build src->new map), then keys+bindings with remap."""
    layer_map = {l["srcId"]: _uid() for l in layers}
    for l in layers:
        conn.execute(
            "INSERT INTO layers (name, order_id, icon_id, profile_id, animation_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (l["name"], base_order + l.get("orderId", 0), l.get("iconId"), profile_id,
             l.get("animationId"), layer_map[l["srcId"]], now, now),
        )
    for l in layers:
        new_lid = layer_map[l["srcId"]]
        for k in l["keys"]:
            new_kid = _uid()
            conn.execute(
                "INSERT INTO keys (color_hex, position_id, layer_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?)",
                (k.get("colorHex") or UNSET_COLOR, k["positionId"], new_lid, new_kid, now, now),
            )
            for b in k.get("bindings", []):
                code = _remap_code(b.get("actionCode"), b.get("actionType"), layer_map, macro_map)
                conn.execute(
                    "INSERT INTO key_bindings (context, action_code, action_type, behavior, key_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (b.get("context"), code, b["actionType"], b["behavior"], new_kid, _uid(), now, now),
                )
    return layer_map


def import_profile(data: dict, name: str | None = None) -> dict:
    if data.get("kind") != "profile":
        raise ValueError("not a profile export")
    conn = connect()
    try:
        now = _now()
        pid = _uid()
        pname = name or data["profile"].get("name", "Imported Profile")
        max_order = conn.execute("SELECT COALESCE(MAX(order_id), -1) FROM profiles").fetchone()[0]
        conn.execute(
            "INSERT INTO profiles (name, order_id, state, icon_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?)",
            (pname, max_order + 1, "FLOW", data["profile"].get("iconId"), pid, now, now),
        )
        macro_map = _create_macros(conn, data.get("macros", []), now)
        _import_layers(conn, pid, data.get("layers", []), now, macro_map)
        conn.commit()
        return {"ok": True, "id": pid, "name": pname}
    finally:
        conn.close()


def import_layer(profile_id: str, data: dict) -> dict:
    if data.get("kind") != "layer":
        raise ValueError("not a layer export")
    conn = connect()
    try:
        now = _now()
        macro_map = _create_macros(conn, data.get("macros", []), now)
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_id), -1) FROM layers WHERE profile_id=?", (profile_id,)
        ).fetchone()[0]
        _import_layers(conn, profile_id, [data["layer"]], now, macro_map, base_order=max_order + 1)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def duplicate_profile(profile_id: str) -> dict:
    """In-DB deep copy. Macros are global/shared, so bindings keep their macro
    refs (empty macro_map); only layer refs are remapped."""
    conn = connect()
    try:
        now = _now()
        payload = _profile_payload(conn, profile_id)
        pid = _uid()
        max_order = conn.execute("SELECT COALESCE(MAX(order_id), -1) FROM profiles").fetchone()[0]
        conn.execute(
            "INSERT INTO profiles (name, order_id, state, icon_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?)",
            (payload["profile"]["name"] + " copy", max_order + 1, "FLOW",
             payload["profile"].get("iconId"), pid, now, now),
        )
        _import_layers(conn, pid, payload["layers"], now, macro_map={})
        conn.commit()
        return {"ok": True, "id": pid}
    finally:
        conn.close()
