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
from ..device import module_fields

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
                        "bays": _bays_for_layer(conn, p["id"], l["id"]),
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


def _bays_for_layer(conn, profile_id: str, layer_id: str) -> dict:
    """{bay location: module config id | "transparent" | "disabled"} for one layer.

    A layer picks which module profile each of the eight bays uses, and the keymap read has been
    importing that since bays were decoded -- but it never reached the UI, so the app could not
    say which module profile a given layer actually runs. Clicking a module on the virtual board
    needs exactly this to open the right profile rather than the first one of that type.
    """
    out = {}
    for r in conn.execute(
        "SELECT module_config_id, binding_location, state FROM module_config_bindings "
        "WHERE profile_id = ? AND layer_id = ?", (profile_id, layer_id)
    ):
        out[r["binding_location"]] = r["state"] or r["module_config_id"]
    return out


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


LAYER_PREFIXES = ("MO_LAYER_", "TO_LAYER_", "TOGGLE_LAYER_", "STICKY_LAYER_")


def layer_references(conn, layer_id: str) -> list[dict]:
    """Keys ANYWHERE in the profile whose binding switches to this layer.

    Deleting a layer strands these. They cannot be repointed automatically -- there is no
    correct answer to "which layer did you mean instead" -- so they are reported so the user
    can be told, and cleared rather than left dangling.
    """
    out = []
    for pre in LAYER_PREFIXES:
        for r in conn.execute(
            "SELECT b.id, l.name AS layer_name, k.position_id, b.behavior "
            "FROM key_bindings b JOIN keys k ON k.id = b.key_id JOIN layers l ON l.id = k.layer_id "
            "WHERE b.action_code = ?", (pre + layer_id,)
        ):
            out.append({"bindingId": r["id"], "layerName": r["layer_name"],
                        "positionId": r["position_id"], "behavior": r["behavior"]})
    return out


def layer_reference_count(layer_id: str) -> dict:
    """For the delete confirmation, before anything is removed."""
    conn = connect()
    try:
        refs = layer_references(conn, layer_id)
        return {"count": len(refs), "keys": refs}
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
        # Keys elsewhere that switch TO this layer would be left pointing at nothing, and a
        # dangling reference is not merely cosmetic: the flash encoder used to resolve an
        # unknown layer to index 0, silently becoming "switch to the base layer".
        #
        # They are REPOINTED by position rather than dropped: whichever layer shifts up into
        # the deleted layer's order takes its place, so a key that meant "go to the third
        # layer" still means that. References to layers that merely SHIFT need nothing -- they
        # are held by uuid and resolved to an index at flash time, so they follow along.
        # Only when nothing takes the vacated position (the last layer was deleted) is the
        # binding cleared, because then there is genuinely nothing to point at.
        stranded = layer_references(conn, layer_id)
        gone_order = conn.execute("SELECT order_id FROM layers WHERE id=?", (layer_id,)).fetchone()["order_id"]
        successor = conn.execute(
            "SELECT id FROM layers WHERE profile_id=? AND order_id>? ORDER BY order_id LIMIT 1",
            (row["profile_id"], gone_order)).fetchone()
        repointed = cleared = 0
        for ref in stranded:
            if successor is not None:
                cur = conn.execute("SELECT action_code FROM key_bindings WHERE id=?",
                                   (ref["bindingId"],)).fetchone()
                prefix = next((p for p in LAYER_PREFIXES if cur["action_code"].startswith(p)), None)
                if prefix:
                    conn.execute("UPDATE key_bindings SET action_code=?, updated_at=? WHERE id=?",
                                 (prefix + successor["id"], _now(), ref["bindingId"]))
                    repointed += 1
                    continue
            conn.execute("DELETE FROM key_bindings WHERE id=?", (ref["bindingId"],))
            cleared += 1

        key_ids = [r["id"] for r in conn.execute("SELECT id FROM keys WHERE layer_id=?", (layer_id,))]
        for kid in key_ids:
            conn.execute("DELETE FROM key_bindings WHERE key_id=?", (kid,))
        conn.execute("DELETE FROM keys WHERE layer_id=?", (layer_id,))
        conn.execute("DELETE FROM layers WHERE id=?", (layer_id,))
        conn.commit()
        return {"ok": True, "repointedReferences": repointed,
                "clearedReferences": cleared, "affected": len(stranded)}
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


def reorder_layers(profile_id: str, ordered_ids: list[str]) -> dict:
    """Set layer order from a full ordered list of this profile's layer ids.

    Layer-switch bindings need no adjustment: they hold the target layer's uuid and are
    resolved to an index only at flash time, so a moved layer keeps its keys and they follow
    it. Order is positional, identity is not.
    """
    conn = connect()
    try:
        have = [r["id"] for r in conn.execute(
            "SELECT id FROM layers WHERE profile_id=? ORDER BY order_id", (profile_id,))]
        if sorted(have) != sorted(ordered_ids):
            # A partial list would silently drop layers to order 0 and collide.
            raise ValueError("the new order must list exactly this profile's layers")
        now = _now()
        for i, lid in enumerate(ordered_ids):
            conn.execute("UPDATE layers SET order_id=?, updated_at=? WHERE id=?", (i, now, lid))
        conn.commit()
        return {"ok": True, "order": ordered_ids}
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


# Dropdown options for module gesture bindings. This holds every action our
# imported defaults use (so you can always reset to a default) plus the obvious
# extras, grouped for the <optgroup> UI. It's intentionally a working set — once
# firmware reverse-engineering shows what the modules can really do, revisit the
# codes/labels. `code` is stored in module_bindings.action_code; the UI shows
# `label`. Any imported value not listed here still renders as a synthetic option.
_CURSOR_V = "mouse - MOUSE_DOWN - MOUSE_UP"
_CURSOR_H = "mouse - MOUSE_LEFT - MOUSE_RIGHT"
MODULE_ACTIONS = [
    {"code": "", "label": "None", "actionType": "none", "group": ""},
    # Cursor / pointer (Touch 1-finger + Track vertical/horizontal)
    {"code": _CURSOR_V, "label": "Vertical Cursor Control", "actionType": "value", "group": "Cursor"},
    {"code": _CURSOR_H, "label": "Horizontal Cursor Control", "actionType": "value", "group": "Cursor"},
    # Scroll
    {"code": "mouse - SCROLL_UP - SCROLL_DOWN", "label": "Vertical Scroll", "actionType": "value", "group": "Scroll"},
    {"code": "mouse - SCROLL_LEFT - SCROLL_RIGHT", "label": "Horizontal Scroll", "actionType": "value", "group": "Scroll"},
    # Mouse buttons
    {"code": "M1", "label": "Left Click", "actionType": "mouse", "group": "Clicks"},
    {"code": "M2", "label": "Right Click", "actionType": "mouse", "group": "Clicks"},
    {"code": "M3", "label": "Middle Click", "actionType": "mouse", "group": "Clicks"},
    {"code": "M4", "label": "Mouse Button 4", "actionType": "mouse", "group": "Clicks"},
    # Media (Tune)
    {"code": "C_VOL_DOWN - C_VOL_UP", "label": "Volume", "actionType": "value", "group": "Media"},
    {"code": "C_PLAY_PAUSE", "label": "Play / Pause", "actionType": "key", "group": "Media"},
    {"code": "C_NEXT", "label": "Next Track", "actionType": "key", "group": "Media"},
    {"code": "C_PREVIOUS", "label": "Previous Track", "actionType": "key", "group": "Media"},
    {"code": "C_FAST_FORWARD", "label": "Fast Forward", "actionType": "key", "group": "Media"},
    {"code": "C_REWIND", "label": "Rewind", "actionType": "key", "group": "Media"},
    {"code": "C_MUTE", "label": "Mute", "actionType": "key", "group": "Media"},
    # Display & LED (Tune)
    {"code": "C_BRIGHTNESS_INC", "label": "Screen Brightness Up", "actionType": "key", "group": "Display & LED"},
    {"code": "C_BRIGHTNESS_DEC", "label": "Screen Brightness Down", "actionType": "key", "group": "Display & LED"},
    {"code": "LED_BRIGHTNESS_UP", "label": "Keyboard LED Brightness Up", "actionType": "LED", "group": "Display & LED"},
    {"code": "LED_BRIGHTNESS_DOWN", "label": "Keyboard LED Brightness Down", "actionType": "LED", "group": "Display & LED"},
    # Shortcuts (Touch swipe defaults)
    {"code": "LCTRL + TAB", "label": "Ctrl + Tab", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LCTRL + LSHIFT + TAB", "label": "Ctrl + Shift + Tab", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + ESC", "label": "Alt + Esc", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + LSHIFT + ESC", "label": "Alt + Shift + Esc", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LGUI + TAB", "label": "Win + Tab", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LGUI + LCTRL + LEFT", "label": "Win + Ctrl + Left", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LGUI + LCTRL + RIGHT", "label": "Win + Ctrl + Right", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + PG_UP", "label": "Alt + Page Up", "actionType": "shortcut_alias", "group": "Shortcuts"},
    {"code": "LALT + PG_DN", "label": "Alt + Page Down", "actionType": "shortcut_alias", "group": "Shortcuts"},
]


def _ensure_touch_defaults(conn) -> None:
    """Backfill the 1-finger cursor gestures NayaFlow renders implicitly for Touch
    (Vertical/Horizontal cursor control + tap = left click), and unify the earlier
    placeholder cursor codes with the real axis codes Track uses. Idempotent."""
    now = _now()
    # migrate the first-pass placeholder codes -> the shared cursor axis codes
    conn.execute("UPDATE module_bindings SET action_code=?, action_type='value' WHERE action_code='CURSOR_VERTICAL'", (_CURSOR_V,))
    conn.execute("UPDATE module_bindings SET action_code=?, action_type='value' WHERE action_code='CURSOR_HORIZONTAL'", (_CURSOR_H,))
    for m in conn.execute("SELECT id FROM module_configs WHERE type='TOUCH'").fetchall():
        cid = m["id"]
        has_one = conn.execute(
            "SELECT 1 FROM module_bindings WHERE module_config_id=? AND behavior LIKE '%:1_finger'",
            (cid,),
        ).fetchone()
        if has_one:
            continue
        for behavior, atype, code in (
            ("vertical:touch:1_finger", "value", _CURSOR_V),
            ("horizontal:touch:1_finger", "value", _CURSOR_H),
            ("tap:touch:1_finger", "mouse", "M1"),
        ):
            conn.execute(
                "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                "invert, threshold, direction, mode, module_config_id, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (None, code, atype, behavior, 0, 0, "+", 0, cid, str(uuid.uuid4()), now, now),
            )
    conn.commit()


# Gesture slots NayaFlow's own vocabulary defines but its editor leaves blank or hides,
# so our UI can bind them. Every string here is verbatim from the recovered enum
# (docs/reference/naya-gesture-enum.json) -- checked by tests/test_gesture_slots.py.
#   * parity gaps: gestures NayaFlow renders (blank) that we dropped entirely, because
#     we build rows from stored bindings and an unbound gesture has no row.
#   * dial split: NayaFlow exposes only a combined dial binding; the enum has each direction
#     separately. Those are fields 0x22/0x23 -- see the retraction note below.
#   * pinch and spread are ONE gesture on this hardware (a single "pinch + tap"), so they are
#     one row rather than the enum's two.
_GESTURE_SLOTS = {
    "TUNE": (
        "tap:tune:1_finger",                    # blank in NayaFlow; device field 0x08
        "pinch:tune:2_fingers",       # rendered "Pinch & Spread": one gesture, not two
        # NayaFlow exposes only the combined "rotate:tune:dial" binding; these are the two
        # halves, at 0x22/0x23. The earlier doubt ("Touch carries the identical pair and has no
        # dial") came from a Touch map probed at a 36-field hybrid slot -- a real Touch config
        # is 31 fields, so those indices were an orphaned tail, not Touch schema.
        "clockwise_rotate:tune:dial",
        "counter_clockwise_rotate:tune:dial",
    ),
    # the renderer spells this "hold:"; "tap_hold:" appears only inside NayaCore
    "TRACK": tuple(f"hold:track:button_{i}" for i in (1, 2, 3, 4)),
    "TOUCH": (
        "tap:touch:1_finger",           # left click; device field 0x0b
        "tap:touch:2_fingers",          # NayaFlow default: right click; device field 0x0c
        "pinch:touch:2_fingers",      # rendered "Pinch & Spread": one gesture, not two
    ),
}


def _ensure_gesture_slots(conn) -> None:
    """Backfill unbound gesture rows so every gesture the module supports is editable.

    Additive and idempotent: only inserts a behavior that has no row yet, and always as
    an unbound ('none') action -- it never touches an existing binding. Rows are created
    up front rather than synthesised in get_modules so the flash/diff path sees ordinary
    bindings with real ids."""
    now = _now()
    for mtype, behaviors in _GESTURE_SLOTS.items():
        for m in conn.execute("SELECT id FROM module_configs WHERE type=?", (mtype,)).fetchall():
            cid = m["id"]
            existing = {
                r["behavior"] for r in conn.execute(
                    "SELECT behavior FROM module_bindings WHERE module_config_id=?", (cid,)
                )
            }
            for behavior in behaviors:
                if behavior in existing:
                    continue
                conn.execute(
                    "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                    "invert, threshold, direction, mode, module_config_id, id, updated_at, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (None, "", "none", behavior, 0, 0, "+", 0, cid, str(uuid.uuid4()), now, now),
                )
    conn.commit()


def set_module_binding(binding_id: str, action_code: str, action_type: str) -> dict:
    """Update a module gesture's assigned action (from the Modules dropdown)."""
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE module_bindings SET action_code=?, action_type=?, updated_at=? WHERE id=?",
            (action_code or "", action_type or "none", _now(), binding_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no module binding {binding_id}")
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
        _ensure_touch_defaults(conn)
        _ensure_gesture_slots(conn)
        configs = []
        for m in conn.execute(
            "SELECT id, name, type, size, order_id, icon_id, variant FROM module_configs "
            "ORDER BY type, order_id"
        ):
            bindings = []
            for b in conn.execute(
                "SELECT id, behavior, action_type, action_code, invert, threshold, "
                "direction, mode FROM module_bindings WHERE module_config_id = ?",
                (m["id"],),
            ):
                parts = (b["behavior"] or "").split(":")
                # Data-backed flashability: does this gesture have a device field, and what
                # action kinds can it hold? (from the recovered module field map)
                field_kind = module_fields.gesture_kind(m["type"], b["behavior"] or "")
                # An axis gesture has no single field, so writable_fields does not list it -- but
                # it very much reaches the device, as two. And a Track hold has a row in the app
                # and nowhere on the board at all.
                flashable = module_fields.gesture_has_device_field(m["type"], b["behavior"] or "")
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
                    "fieldKind": field_kind,      # 'keypress'/'mouse_button'/'axis'/None
                    "flashable": flashable,       # True = we can write it (proved live in C1/C2)
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
            halves = module_fields.splittable_axes(m["type"])
            axes = []
            for gesture, spec in halves.items():   # already in display order
                rows = [b for b in conn.execute(
                    "SELECT action_code, direction, invert FROM module_bindings "
                    "WHERE module_config_id=? AND behavior=?", (m["id"], gesture))]
                per = {}
                for r in rows:
                    code = r["action_code"] or ""
                    if code and " - " not in code:      # a per-half key, not the combined form
                        per[r["direction"] or "+"] = code
                # The unsplit form is one row holding BOTH directions -- "mouse - MOUSE_LEFT -
                # MOUSE_RIGHT" or "C_VOL_DOWN - C_VOL_UP". The last two parts are the two halves,
                # in - then + order, and the UI must show them: "motion" alone tells the user
                # nothing about what the axis does.
                combined = next((r["action_code"] for r in rows
                                 if r["action_code"] and " - " in r["action_code"]), "")
                parts = [x.strip() for x in combined.split(" - ")] if combined else []
                axes.append({
                    "behavior": gesture,
                    "fields": {"-": spec["-"], "+": spec["+"]},
                    "minus": per.get("-"),
                    "plus": per.get("+"),
                    "defaultMinus": parts[-2] if len(parts) >= 2 else None,
                    "defaultPlus": parts[-1] if len(parts) >= 2 else None,
                    "split": bool(per),
                    "invert": any(r["invert"] for r in rows),
                })
            # A paired gesture (the Tune dial) is one row until it is split, then two. The UI
            # hides the halves until then, so it needs to know which rows are halves.
            pairs = []
            for combined, halves in module_fields.paired_gestures(m["type"]).items():
                codes = {}
                for side, gesture in halves.items():
                    row = conn.execute(
                        "SELECT action_code FROM module_bindings WHERE module_config_id=? "
                        "AND behavior=?", (m["id"], gesture)).fetchone()
                    codes[side] = (row["action_code"] or "") if row else ""
                pairs.append({
                    "behavior": combined,
                    "minusBehavior": halves["-"], "plusBehavior": halves["+"],
                    "minus": codes.get("-") or None, "plus": codes.get("+") or None,
                    "split": any(codes.values()),
                })
            configs.append({
                "id": m["id"],
                "name": m["name"],
                "type": m["type"],
                "pairs": pairs,
                # Axis gestures occupy two device fields and each half can hold a key instead of
                # motion; the UI needs both halves to offer that.
                "axes": axes,
                # Track ships two asymmetric variants and a profile belongs to exactly one of
                # them, so the left and right bays must offer different lists.
                "variant": m["variant"],
                "size": m["size"],
                "orderId": m["order_id"],
                "bindings": bindings,
                "settingsSchema": settings_schema,
            })
        return {"modules": configs, "actions": MODULE_ACTIONS}
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


def set_layer_bay(layer_id: str, module_type: str, config_id: str | None,
                  side: str | None = None) -> dict:
    """Choose which module profile one layer runs in a bay.

    A symmetric module (Touch, Tune) is set on BOTH sides from a single choice -- the same
    profile behaves identically in either hand, so splitting it would be two controls that are
    always set the same. Track is asymmetric hardware, so its sides are chosen separately and
    the caller passes `side`.

    `config_id` of None means inherit (the layer follows the base layer) and "disabled" means
    the bay is off on this layer. Both are stored in `state`, which is how NayaFlow's own schema
    distinguishes them from a real profile reference.
    """
    from ..device.module_layout import BAY_POSITIONS

    module_type = (module_type or "").upper()
    if module_type not in BAY_POSITIONS:
        raise ValueError(f"unknown module type {module_type!r}")
    sides = [side] if side else list(BAY_POSITIONS[module_type])
    for s in sides:
        if s not in BAY_POSITIONS[module_type]:
            raise ValueError(f"unknown side {s!r}")

    conn = connect()
    try:
        row = conn.execute("SELECT profile_id FROM layers WHERE id=?", (layer_id,)).fetchone()
        if row is None:
            raise ValueError(f"no layer {layer_id}")
        profile_id, now = row["profile_id"], _now()

        if config_id and config_id not in ("transparent", "disabled"):
            if conn.execute("SELECT 1 FROM module_configs WHERE id=? AND type=?",
                            (config_id, module_type)).fetchone() is None:
                raise ValueError(f"no {module_type} profile {config_id}")

        for s in sides:
            location = f"{module_type.lower()}:keyboard_{s}"
            conn.execute("DELETE FROM module_config_bindings WHERE profile_id=? AND layer_id=? "
                         "AND binding_location=?", (profile_id, layer_id, location))
            if config_id == "disabled":
                state, cfg = "disabled", None
            elif not config_id or config_id == "transparent":
                state, cfg = "transparent", None
            else:
                state, cfg = None, config_id
            conn.execute(
                "INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                "binding_location, state, updated_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (profile_id, layer_id, cfg, location, state, now, now))
        conn.commit()
        return {"ok": True, "sides": sides, "configId": config_id}
    finally:
        conn.close()


def set_axis_split(config_id: str, behavior: str, half: str, action_code: str | None) -> dict:
    """Bind one half of an axis gesture to a key, or clear it back to motion.

    An axis gesture occupies TWO device fields, one per direction, and either can hold a keypress
    instead of the motion record -- that is what NayaFlow's "split" does (capture 2026-09-03).
    The halves are stored as separate rows keyed by the `direction` column; the stock single row
    with a combined "mouse - LEFT - RIGHT" code means neither half is bound to a key.

    `half` is "-" or "+". `action_code` of None clears that half back to motion.
    """
    from ..device.module_fields import axis_halves

    if half not in ("-", "+"):
        raise ValueError(f"half must be '-' or '+', got {half!r}")
    conn = connect()
    try:
        row = conn.execute("SELECT type FROM module_configs WHERE id=?", (config_id,)).fetchone()
        if row is None:
            raise ValueError(f"no module config {config_id}")
        if behavior not in axis_halves(row["type"]):
            raise ValueError(f"{behavior!r} is not a splittable axis on a {row['type']}")

        now = _now()
        conn.execute("DELETE FROM module_bindings WHERE module_config_id=? AND behavior=? "
                     "AND direction=? AND action_code NOT LIKE '% - %'",
                     (config_id, behavior, half))
        if action_code:
            conn.execute(
                "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                "invert, threshold, direction, mode, module_config_id, id, updated_at, created_at)"
                " VALUES (NULL,?,?,?,0,0,?,0,?,?,?,?)",
                (action_code, "key", behavior, half, config_id, str(uuid.uuid4()), now, now))
        conn.commit()
        return {"ok": True, "behavior": behavior, "half": half, "actionCode": action_code}
    finally:
        conn.close()


def set_axis_invert(config_id: str, behavior: str, invert: bool) -> dict:
    """Flip an axis gesture's direction.

    At the device level inverting IS writing the opposite selector signs -- there is no invert
    flag in the config anywhere. NayaFlow has the control but never writes anything for it, which
    is why toggling it there does nothing (capture 2026-09-03: zero writes).
    """
    from ..device.module_fields import axis_halves

    conn = connect()
    try:
        row = conn.execute("SELECT type FROM module_configs WHERE id=?", (config_id,)).fetchone()
        if row is None:
            raise ValueError(f"no module config {config_id}")
        if behavior not in axis_halves(row["type"]):
            raise ValueError(f"{behavior!r} is not an axis gesture on a {row['type']}")
        cur = conn.execute("UPDATE module_bindings SET invert=?, updated_at=? "
                           "WHERE module_config_id=? AND behavior=?",
                           (1 if invert else 0, _now(), config_id, behavior))
        if cur.rowcount == 0:
            raise ValueError(f"no {behavior!r} binding on this profile")
        conn.commit()
        return {"ok": True, "behavior": behavior, "invert": bool(invert)}
    finally:
        conn.close()
