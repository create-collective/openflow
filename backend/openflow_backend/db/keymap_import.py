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

from ..device import keymap_read as kr
from datetime import datetime, timezone

from ..device.keymap_read import decode_keymap
from .database import connect

UNSET_COLOR = "#xxxxxx"
KEYS_PER_LAYER = 97  # position_id 0..96


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _import_bays(conn, profile_id, order_to_layer, read, slot_uuid, now) -> int:
    """Persist which module profile each bay uses, per layer.

    This is what the virtual board's module slots should show. Until now they were a
    localStorage toy -- {left, right} with no connection to the device at all -- so reading the
    keyboard could not update them because there was nothing to update.

    Rows go in module_config_bindings, which is NayaFlow's own table for exactly this and whose
    binding_location values match the bay layout we decoded from the layer data.
    """
    n = 0
    # A bay can point at a slot holding a config we have never seen -- NayaFlow allocates its own
    # slots, and one of ours is currently carrying a profile it created. Recording that bay would
    # violate the foreign key and take the whole keymap read down with it, so the config has to
    # exist here, not merely be present on the device.
    # ...and it has to be a profile of the bay's own type: the board's bay byte can point at
    # any slot, and a slot holding a Track profile is no Tune profile. Recording that put a
    # Track id in a Tune bay (2026-09-17); the bay is left unset and follows the base layer.
    known = {r["id"]: r["type"] for r in conn.execute("SELECT id, type FROM module_configs")}
    conn.execute("DELETE FROM module_config_bindings WHERE profile_id=?", (profile_id,))
    for order, bays in (read.get("bays") or {}).items():
        lid = order_to_layer.get(int(order))
        if lid is None:
            continue
        for location, value in bays.items():
            if value == "transparent":
                state, cfg = "transparent", None
            elif value == "disabled":
                state, cfg = "disabled", None
            else:
                cfg = slot_uuid.get(value)
                if cfg is None or cfg not in known:
                    continue          # a slot we have no config for: record nothing, invent nothing
                if known[cfg] != location.split(":", 1)[0].upper():
                    continue          # a profile of another type: not this bay's to hold
                state = None
            conn.execute(
                "INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                "binding_location, state, updated_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (profile_id, lid, cfg, location, state, now, now))
            n += 1
    return n


def import_read(read: dict, profile_name: str | None = None,
                slot_uuid: dict | None = None) -> dict:
    """Create or update a profile from a raw device read. Returns a summary dict.

    `slot_uuid` maps module-config SLOT -> config uuid, from the device's module config list.
    Without it the bays cannot be resolved to profiles and are skipped rather than guessed at.
    """
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
        # The board's per-layer LED animation, byte 2 of the layer-list entry. Read it back so a
        # profile imported from a keyboard keeps its effects instead of coming in as solid.
        animations = read.get("layer_animations") or {}
        # Older databases and the test fixtures predate the column. A missing LED animation must
        # not stop a keymap being imported.
        has_anim = "animation_id" in {r[1] for r in conn.execute("PRAGMA table_info(layers)")}
        for order in sorted(read["layers"]):
            lid = device_uuids.get(order) or str(uuid.uuid4())
            order_to_layer[order] = lid
            anim = kr.LAYER_ANIMATIONS.get(int(animations.get(order, 0)))
            if lid in known:
                if has_anim:
                    conn.execute("UPDATE layers SET order_id=?, animation_id=?, updated_at=? "
                                 "WHERE id=?", (order, anim, now, lid))   # keep the user's name
                else:
                    conn.execute("UPDATE layers SET order_id=?, updated_at=? WHERE id=?",
                                 (order, now, lid))
            elif has_anim:
                conn.execute(
                    "INSERT INTO layers (name, order_id, animation_id, profile_id, id, updated_at, "
                    "created_at) VALUES (?,?,?,?,?,?,?)",
                    (f"Layer {order}", order, anim, prof_id, lid, now, now),
                )
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
        module_colours = decoded.pop("_module_colours", {})
        warnings = decoded.pop("_warnings", [])
        dropped = decoded.pop("_dropped", [])

        # The two module bay blocks, read from their first LED (88 / 112). They are the layer's
        # module colours, not key colours -- without this a board read populated key rows 88-96
        # and left `module_led_*` empty, so the app never knew what the bays showed and a later
        # flash could only leak those key rows back onto the left bay.
        layer_cols = {r[1] for r in conn.execute("PRAGMA table_info(layers)")}
        if {"module_led_left", "module_led_right"} <= layer_cols:
            for order, sides in module_colours.items():
                lid = order_to_layer.get(order)
                if lid is None:
                    continue
                conn.execute("UPDATE layers SET module_led_left=?, module_led_right=?, updated_at=? "
                             "WHERE id=?", (sides.get("left"), sides.get("right"), now, lid))

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

        bays = _import_bays(conn, prof_id, order_to_layer, read, slot_uuid or {}, now)

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
