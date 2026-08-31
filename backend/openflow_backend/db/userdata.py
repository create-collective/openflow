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

# NayaFlow's on-board data stores the primary slot as 'press'; we present it as
# 'tap' (they are the same behaviour) and treat both as the tap slot on write.
TAP_ALIASES = ("tap", "press")


def _norm_behavior(behavior: str) -> str:
    return "tap" if behavior in TAP_ALIASES else behavior


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
    keys: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        kid = r["key_id"]
        if kid not in keys:
            keys[kid] = {
                "id": kid,
                "positionId": r["position_id"],
                "colorHex": None if r["color_hex"] in (None, UNSET_COLOR) else r["color_hex"],
                "bindings": {},  # behavior -> binding
            }
            order.append(kid)
        if r["binding_id"] is not None:
            beh = _norm_behavior(r["behavior"])
            keys[kid]["bindings"][beh] = {
                "id": r["binding_id"],
                "behavior": beh,
                "actionType": r["action_type"],
                "actionCode": r["action_code"],
                "context": r["context"],
            }
    out = []
    for kid in order:
        k = keys[kid]
        # Convenience: the tap binding is what the board legend shows.
        k["binding"] = k["bindings"].get("tap")
        out.append(k)
    return out


def _behavior_match(behavior: str) -> tuple[str, ...]:
    """Which stored behavior values count as the same slot as `behavior`."""
    return TAP_ALIASES if _norm_behavior(behavior) == "tap" else (behavior,)


def set_key_binding(
    layer_id: str,
    position_id: int,
    action_code: str,
    action_type: str,
    behavior: str = "tap",
    context: str | None = None,
) -> dict:
    """Create or update one behavior slot on (layer_id, position_id). Offline write."""
    behavior = _norm_behavior(behavior)
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
        match = _behavior_match(behavior)
        placeholders = ",".join("?" * len(match))
        existing = conn.execute(
            f"SELECT id FROM key_bindings WHERE key_id = ? AND behavior IN ({placeholders})",
            (key_id, *match),
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
        return {"ok": True, "keyId": key_id, "binding": {
            "id": binding_id, "behavior": behavior, "actionType": action_type,
            "actionCode": action_code, "context": context,
        }}
    finally:
        conn.close()


def clear_key_binding(layer_id: str, position_id: int, behavior: str | None = None) -> dict:
    """Remove one behavior slot (or all, if behavior is None) from a key."""
    conn = connect()
    try:
        key = conn.execute(
            "SELECT id FROM keys WHERE layer_id = ? AND position_id = ?",
            (layer_id, position_id),
        ).fetchone()
        if key is None:
            raise ValueError(f"no key at layer={layer_id} position={position_id}")
        if behavior is None:
            conn.execute("DELETE FROM key_bindings WHERE key_id = ?", (key["id"],))
        else:
            match = _behavior_match(behavior)
            placeholders = ",".join("?" * len(match))
            conn.execute(
                f"DELETE FROM key_bindings WHERE key_id = ? AND behavior IN ({placeholders})",
                (key["id"], *match),
            )
        conn.commit()
        return {"ok": True, "keyId": key["id"]}
    finally:
        conn.close()


KEYS_PER_LAYER = 97  # position_id 0-96, matching the recovered data


def create_layer(profile_id: str, name: str) -> dict:
    """Create a new layer under a profile with a full set of (unbound) keys."""
    conn = connect()
    try:
        now = _now()
        lid = str(uuid.uuid4())
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_id), -1) FROM layers WHERE profile_id=?", (profile_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO layers (name, order_id, profile_id, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name, max_order + 1, profile_id, lid, now, now),
        )
        for pos in range(KEYS_PER_LAYER):
            conn.execute(
                "INSERT INTO keys (color_hex, position_id, layer_id, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (UNSET_COLOR, pos, lid, str(uuid.uuid4()), now, now),
            )
        conn.commit()
        return {"ok": True, "id": lid, "name": name}
    finally:
        conn.close()


def rename_layer(layer_id: str, name: str) -> dict:
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE layers SET name=?, updated_at=? WHERE id=?", (name, _now(), layer_id)
        )
        if cur.rowcount == 0:
            raise ValueError(f"no layer {layer_id}")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def delete_layer(layer_id: str) -> dict:
    conn = connect()
    try:
        row = conn.execute("SELECT profile_id FROM layers WHERE id=?", (layer_id,)).fetchone()
        if row is None:
            raise ValueError(f"no layer {layer_id}")
        n = conn.execute(
            "SELECT COUNT(*) FROM layers WHERE profile_id=?", (row["profile_id"],)
        ).fetchone()[0]
        if n <= 1:
            raise ValueError("cannot delete the only layer")
        key_ids = [r["id"] for r in conn.execute("SELECT id FROM keys WHERE layer_id=?", (layer_id,))]
        for kid in key_ids:
            conn.execute("DELETE FROM key_bindings WHERE key_id=?", (kid,))
        conn.execute("DELETE FROM keys WHERE layer_id=?", (layer_id,))
        conn.execute("DELETE FROM layers WHERE id=?", (layer_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def duplicate_layer(layer_id: str) -> dict:
    """Copy a layer with all its keys, colors, and bindings."""
    conn = connect()
    try:
        now = _now()
        src = conn.execute(
            "SELECT name, profile_id, icon_id, animation_id FROM layers WHERE id=?", (layer_id,)
        ).fetchone()
        if src is None:
            raise ValueError(f"no layer {layer_id}")
        new_lid = str(uuid.uuid4())
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_id), -1) FROM layers WHERE profile_id=?", (src["profile_id"],)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO layers (name, order_id, icon_id, profile_id, animation_id, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (f"{src['name']} copy", max_order + 1, src["icon_id"], src["profile_id"],
             src["animation_id"], new_lid, now, now),
        )
        for k in conn.execute(
            "SELECT id, color_hex, position_id FROM keys WHERE layer_id=?", (layer_id,)
        ).fetchall():
            new_kid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO keys (color_hex, position_id, layer_id, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (k["color_hex"], k["position_id"], new_lid, new_kid, now, now),
            )
            for b in conn.execute(
                "SELECT context, action_code, action_type, behavior FROM key_bindings WHERE key_id=?",
                (k["id"],),
            ).fetchall():
                conn.execute(
                    "INSERT INTO key_bindings (context, action_code, action_type, behavior, key_id, id, updated_at, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (b["context"], b["action_code"], b["action_type"], b["behavior"],
                     new_kid, str(uuid.uuid4()), now, now),
                )
        conn.commit()
        return {"ok": True, "id": new_lid}
    finally:
        conn.close()


def set_base_layer(layer_id: str) -> dict:
    """Make a layer the base (order_id 0); shift the others after it."""
    conn = connect()
    try:
        row = conn.execute("SELECT profile_id FROM layers WHERE id=?", (layer_id,)).fetchone()
        if row is None:
            raise ValueError(f"no layer {layer_id}")
        others = [
            r["id"] for r in conn.execute(
                "SELECT id FROM layers WHERE profile_id=? AND id!=? ORDER BY order_id",
                (row["profile_id"], layer_id),
            )
        ]
        now = _now()
        conn.execute("UPDATE layers SET order_id=0, updated_at=? WHERE id=?", (now, layer_id))
        for i, oid in enumerate(others, start=1):
            conn.execute("UPDATE layers SET order_id=?, updated_at=? WHERE id=?", (i, now, oid))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def set_layer_animation(layer_id: str, animation: str | None) -> dict:
    """Set a layer's LED animation (solid/swirl/breathe/spectrum, or None)."""
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE layers SET animation_id=?, updated_at=? WHERE id=?",
            (animation, _now(), layer_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no layer {layer_id}")
        conn.commit()
        return {"ok": True, "animation": animation}
    finally:
        conn.close()


def fill_layer_color(layer_id: str, color_hex: str | None) -> dict:
    """Paint every key on a layer one color (the Fill tool)."""
    conn = connect()
    try:
        value = color_hex if color_hex else UNSET_COLOR
        conn.execute(
            "UPDATE keys SET color_hex=?, updated_at=? WHERE layer_id=?",
            (value, _now(), layer_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# Per-module-type settings schema (from NayaFlow's settings tabs). Editing stores
# values in module_settings keyed by the field id.
_COMMON_POINTER = [
    {"id": "scroll_speed", "label": "Scroll Speed", "desc": "Adjust the scrolling speed",
     "kind": "slider", "min": 1, "max": 100, "default": 50},
    {"id": "pointer_speed", "label": "Pointer Speed", "desc": "Adjust the pointer movement speed",
     "kind": "slider", "min": 1, "max": 100, "default": 10},
    {"id": "pointer_accel", "label": "Pointer Acceleration", "desc": "Adjust the pointer acceleration curve",
     "kind": "slider", "min": 1, "max": 100, "default": 50},
    {"id": "pointer_accel_on", "label": "Pointer Acceleration ON/OFF",
     "desc": "Enable or disable pointer acceleration", "kind": "toggle", "default": True},
]
SETTINGS_SCHEMA = {
    "TOUCH": _COMMON_POINTER,
    "TRACK": _COMMON_POINTER,
    "TUNE": _COMMON_POINTER + [
        {"id": "ticks_per_rotation", "label": "Ticks Per Rotation",
         "desc": "Number of tactile feedback ticks per full rotation", "kind": "slider",
         "min": 5, "max": 170, "default": 72},
        {"id": "tick_strength", "label": "Set Tick Strength",
         "desc": "Adjust the tactile feedback strength of crown ticks", "kind": "slider",
         "min": 0, "max": 100, "default": 75},
        {"id": "toggle_ticks", "label": "Toggle Ticks",
         "desc": "Enable or disable tactile feedback ticks", "kind": "toggle", "default": True},
    ],
}


def set_module_setting(config_id: str, field_id: str, value) -> dict:
    """Upsert a module setting value (keyed by the schema field id)."""
    conn = connect()
    try:
        now = _now()
        val = "true" if value is True else "false" if value is False else str(value)
        existing = conn.execute(
            "SELECT 1 FROM module_settings WHERE module_config_id=? AND correlation_id=?",
            (config_id, field_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE module_settings SET value=?, updated_at=? WHERE module_config_id=? AND correlation_id=?",
                (val, now, config_id, field_id),
            )
        else:
            conn.execute(
                "INSERT INTO module_settings (value, type, correlation_id, module_config_id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (val, "openflow", field_id, config_id, now, now),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def get_modules() -> dict:
    """Module configs grouped by type, each with its gesture bindings + settings.

    behavior encodes 'gesture:module[:target]' (e.g. 'vertical:track',
    'tap:track:button_1'); action_code for axes uses ' - ' separators
    (e.g. 'mouse - SCROLL_UP - SCROLL_DOWN'). We return the raw values and a
    parsed gesture/target so the UI can group axes vs buttons.
    """
    conn = connect()
    try:
        configs = []
        for m in conn.execute(
            "SELECT id, name, type, size, order_id, icon_id FROM module_configs ORDER BY type, order_id"
        ):
            bindings = []
            for b in conn.execute(
                "SELECT id, behavior, action_type, action_code, invert, threshold, "
                "direction, mode FROM module_bindings WHERE module_config_id = ?",
                (m["id"],),
            ):
                parts = (b["behavior"] or "").split(":")
                bindings.append({
                    "id": b["id"],
                    "behavior": b["behavior"],
                    "gesture": parts[0] if parts else None,
                    "target": parts[2] if len(parts) > 2 else None,
                    "actionType": b["action_type"],
                    "actionCode": b["action_code"],
                    "invert": bool(b["invert"]),
                    "threshold": b["threshold"],
                    "direction": b["direction"],
                    "mode": b["mode"],
                })
            stored = {
                s["correlation_id"]: s["value"]
                for s in conn.execute(
                    "SELECT correlation_id, value FROM module_settings WHERE module_config_id = ?",
                    (m["id"],),
                )
            }
            schema = SETTINGS_SCHEMA.get(m["type"], _COMMON_POINTER)
            settings_schema = []
            for f in schema:
                cur = stored.get(f["id"], f["default"])
                if f["kind"] == "toggle":
                    cur = (str(cur).lower() == "true") if not isinstance(cur, bool) else cur
                else:
                    try:
                        cur = int(cur)
                    except (TypeError, ValueError):
                        cur = f["default"]
                settings_schema.append({**f, "value": cur})
            configs.append({
                "id": m["id"],
                "name": m["name"],
                "type": m["type"],
                "size": m["size"],
                "orderId": m["order_id"],
                "bindings": bindings,
                "settingsSchema": settings_schema,
            })
        return {"modules": configs}
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
