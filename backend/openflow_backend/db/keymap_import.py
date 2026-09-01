"""Import a keymap read off the device into the user-data DB as a new profile.

Consumes the raw read from device/keymap_read.read_keymap and the decoder in the
same module, and writes a profile -> layers -> keys -> key_bindings tree plus the
per-key LED colours. Layer names aren't stored on the device, so layers are named
"Layer 0", "Layer 1", ... to match the UI's 0-indexed display.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..device.keymap_read import decode_keymap
from .database import connect

UNSET_COLOR = "#xxxxxx"
KEYS_PER_LAYER = 97  # position_id 0..96


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def import_read(read: dict, profile_name: str | None = None) -> dict:
    """Create a new profile from a raw device read. Returns a summary dict."""
    now = _now()
    name = profile_name or f"Read from keyboard {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    conn = connect()
    try:
        prof_id = str(uuid.uuid4())
        # New profiles sort to the top; leave existing ones untouched (non-destructive).
        conn.execute(
            "INSERT INTO profiles (name, order_id, state, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name, 0, "ON_BOARD", prof_id, now, now),
        )

        # Create one layer per device layer index, with a full set of unbound keys.
        order_to_layer: dict[int, str] = {}
        key_ids: dict[int, dict[int, str]] = {}
        for order in sorted(read["layers"]):
            lid = str(uuid.uuid4())
            order_to_layer[order] = lid
            conn.execute(
                "INSERT INTO layers (name, order_id, profile_id, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (f"Layer {order}", order, prof_id, lid, now, now),
            )
            key_ids[order] = {}
            for pos in range(KEYS_PER_LAYER):
                kid = str(uuid.uuid4())
                key_ids[order][pos] = kid
                conn.execute(
                    "INSERT INTO keys (color_hex, position_id, layer_id, id, updated_at, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (UNSET_COLOR, pos, lid, kid, now, now),
                )

        # Decode bindings + colours now that layer ids exist (for layer-switch codes).
        decoded = decode_keymap(read, order_to_layer)
        colors = decoded.pop("_colors", {})
        warnings = decoded.pop("_warnings", [])
        dropped = decoded.pop("_dropped", [])

        n_bindings = 0
        for order, positions in decoded.items():
            for pos, slots in positions.items():
                kid = key_ids.get(order, {}).get(pos)
                if kid is None:
                    continue
                for beh, atype, code in slots:
                    conn.execute(
                        "INSERT INTO key_bindings (context, action_code, action_type, behavior, "
                        "key_id, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (None, str(code), atype, beh, kid, str(uuid.uuid4()), now, now),
                    )
                    n_bindings += 1

        for order, cmap in colors.items():
            for pos, hexv in cmap.items():
                kid = key_ids.get(order, {}).get(pos)
                if kid is not None:
                    conn.execute("UPDATE keys SET color_hex=?, updated_at=? WHERE id=?",
                                 (hexv, now, kid))

        conn.commit()
        return {
            "ok": True,
            "profileId": prof_id,
            "name": name,
            "layers": len(order_to_layer),
            "bindings": n_bindings,
            "warnings": warnings,
            "dropped": dropped,
        }
    finally:
        conn.close()
