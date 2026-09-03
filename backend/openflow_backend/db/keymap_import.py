"""Import a keymap read off the device into the user-data DB.

Consumes the raw read from device/keymap_read.read_keymap and the decoder in the same
module, and writes a profile -> layers -> keys -> key_bindings tree plus the per-key LED
colours.

**Names are not on the keyboard -- UUIDs are.** Each layer-list entry carries a 16-byte UUID
and no name, so a name is purely app-side. But the UUID is a stable identity, which means a
re-read can be matched to the layers it already knows: those keep their user-given names, and
only genuinely new UUIDs get an enumerated "Layer N". Before this, every read minted fresh
UUIDs and created another profile, which is how a single keyboard ended up represented three
times over.
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
    device_uuids = read.get("layer_uuids") or {}
    conn = connect()
    try:
        # Does the board's layer identity already exist here? If so this is a RE-read of a
        # keyboard we know, and we update it in place so names survive.
        known = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, name, profile_id FROM layers WHERE id IN (%s)"
            % ",".join("?" * len(device_uuids)), tuple(device_uuids.values()))} if device_uuids else {}
        owners = {k["profile_id"] for k in known.values()}
        reuse = known and len(owners) == 1
        prof_id = next(iter(owners)) if reuse else str(uuid.uuid4())
        if reuse:
            row = conn.execute("SELECT name FROM profiles WHERE id=?", (prof_id,)).fetchone()
            name = profile_name or (row["name"] if row else name)
            conn.execute("UPDATE profiles SET updated_at=? WHERE id=?", (now, prof_id))
            # replace this profile's contents; the layer rows themselves are kept for their names
            conn.execute("DELETE FROM key_bindings WHERE key_id IN "
                         "(SELECT k.id FROM keys k JOIN layers l ON l.id=k.layer_id WHERE l.profile_id=?)",
                         (prof_id,))
            conn.execute("DELETE FROM keys WHERE layer_id IN (SELECT id FROM layers WHERE profile_id=?)",
                         (prof_id,))
        else:
            # New profiles sort to the top; leave existing ones untouched (non-destructive).
            conn.execute(
                "INSERT INTO profiles (name, order_id, state, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (name, 0, "ON_BOARD", prof_id, now, now),
            )

        # One layer per device layer index, keyed by the DEVICE's uuid so the next read matches.
        order_to_layer: dict[int, str] = {}
        key_ids: dict[int, dict[int, str]] = {}
        for order in sorted(read["layers"]):
            lid = device_uuids.get(order) or str(uuid.uuid4())
            order_to_layer[order] = lid
            if lid in known:
                conn.execute("UPDATE layers SET order_id=?, updated_at=? WHERE id=?",
                             (order, now, lid))          # keep the user's name
            else:
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
