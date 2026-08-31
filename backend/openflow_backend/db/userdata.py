"""User-data queries: profiles -> layers -> keys -> bindings.

Shapes the recovered NayaFlow schema into the nested structure the keymap editor
needs. Works fully offline against the SQLite store, exactly as NayaFlow persisted
edits without a device connected.

Real-data facts this relies on (from the recovered user-data.db):
  - a key is identified by (layer_id, position_id 0-96)
  - each key has 0 or 1 key_bindings row
  - behavior is 'press' for key bindings in practice (other slots are legal)
  - layer switch: action_type='layer_polite_hold', action_code='MO_LAYER_<layerId>'
    (also TO_LAYER_/TOGGLE_LAYER_/STICKY_LAYER_ prefixes for the other layer types)
  - disabled key: action_type='none', action_code='DISABLE'
  - keys.color_hex uses the sentinel '#xxxxxx' when unset
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .database import connect

UNSET_COLOR = "#xxxxxx"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _binding_dict(row) -> dict | None:
    if row is None or row["binding_id"] is None:
        return None
    return {
        "id": row["binding_id"],
        "behavior": row["behavior"],
        "actionType": row["action_type"],
        "actionCode": row["action_code"],
        "context": row["context"],
    }


def get_userdata() -> dict:
    """Return every profile with its layers, keys, and bindings."""
    conn = connect()
    try:
        profiles = []
        for p in conn.execute(
            "SELECT id, name, state, order_id, icon_id FROM profiles ORDER BY order_id"
        ):
            layers = []
            for l in conn.execute(
                "SELECT id, name, order_id, icon_id, animation_id FROM layers "
                "WHERE profile_id = ? ORDER BY order_id",
                (p["id"],),
            ):
                keys = _keys_for_layer(conn, l["id"])
                layers.append(
                    {
                        "id": l["id"],
                        "name": l["name"],
                        "orderId": l["order_id"],
                        "iconId": l["icon_id"],
                        "animationId": l["animation_id"],
                        "keys": keys,
                    }
                )
            profiles.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "state": p["state"],
                    "orderId": p["order_id"],
                    "iconId": p["icon_id"],
                    "layers": layers,
                }
            )
        return {"profiles": profiles}
    finally:
        conn.close()


def _keys_for_layer(conn, layer_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT k.id AS key_id, k.position_id, k.color_hex,
               b.id AS binding_id, b.behavior, b.action_type, b.action_code, b.context
        FROM keys k
        LEFT JOIN key_bindings b ON b.key_id = k.id
        WHERE k.layer_id = ?
        ORDER BY k.position_id
        """,
        (layer_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r["key_id"],
                "positionId": r["position_id"],
                "colorHex": None if r["color_hex"] in (None, UNSET_COLOR) else r["color_hex"],
                "binding": _binding_dict(r),
            }
        )
    return out


def set_key_binding(
    layer_id: str,
    position_id: int,
    action_code: str,
    action_type: str,
    behavior: str = "press",
    context: str | None = None,
) -> dict:
    """Create or update the binding on (layer_id, position_id). Offline write."""
    conn = connect()
    try:
        key = conn.execute(
            "SELECT id FROM keys WHERE layer_id = ? AND position_id = ?",
            (layer_id, position_id),
        ).fetchone()
        if key is None:
            raise ValueError(f"no key at layer={layer_id} position={position_id}")
        key_id = key["id"]
        now = _now()
        existing = conn.execute(
            "SELECT id FROM key_bindings WHERE key_id = ?", (key_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE key_bindings SET action_code=?, action_type=?, behavior=?, "
                "context=?, updated_at=? WHERE id=?",
                (action_code, action_type, behavior, context, now, existing["id"]),
            )
            binding_id = existing["id"]
        else:
            binding_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO key_bindings "
                "(context, action_code, action_type, behavior, key_id, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (context, action_code, action_type, behavior, key_id, binding_id, now, now),
            )
        conn.commit()
        return {
            "ok": True,
            "keyId": key_id,
            "binding": {
                "id": binding_id,
                "behavior": behavior,
                "actionType": action_type,
                "actionCode": action_code,
                "context": context,
            },
        }
    finally:
        conn.close()


def clear_key_binding(layer_id: str, position_id: int) -> dict:
    """Remove the binding on a key (leaves the key present, unbound)."""
    conn = connect()
    try:
        key = conn.execute(
            "SELECT id FROM keys WHERE layer_id = ? AND position_id = ?",
            (layer_id, position_id),
        ).fetchone()
        if key is None:
            raise ValueError(f"no key at layer={layer_id} position={position_id}")
        conn.execute("DELETE FROM key_bindings WHERE key_id = ?", (key["id"],))
        conn.commit()
        return {"ok": True, "keyId": key["id"]}
    finally:
        conn.close()


def set_key_color(layer_id: str, position_id: int, color_hex: str | None) -> dict:
    """Set a key's LED color (used by the Color page). None clears to sentinel."""
    conn = connect()
    try:
        now = _now()
        value = color_hex if color_hex else UNSET_COLOR
        cur = conn.execute(
            "UPDATE keys SET color_hex=?, updated_at=? WHERE layer_id=? AND position_id=?",
            (value, now, layer_id, position_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no key at layer={layer_id} position={position_id}")
        conn.commit()
        return {"ok": True, "colorHex": color_hex}
    finally:
        conn.close()
