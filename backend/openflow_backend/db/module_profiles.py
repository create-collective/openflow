"""Create, rename and delete module profiles.

A module can have MORE THAN ONE profile, and each layer picks which one is active (the device
stores that as a slot number in the layer's bay record). NayaFlow exposes this badly; the device
supports it cleanly, so OpenFlow models it directly:

  * a profile belongs to a module TYPE (TOUCH / TRACK / TUNE / FLOAT)
  * Track has two stock variants because the module is ASYMMETRIC -- flipping it to the other
    side reverses the physical button order and the scroll direction -- so "Track Left" and
    "Track Right" ship different default maps. Either can occupy either bay; the variant is
    about the bindings, not the position.
  * a new profile is seeded from the stock map so it is usable immediately, then edited.

Names live only here. The device stores a 16-byte UUID per config and no name at all, so the
UUID is the join key that lets a name survive a read (see keymap_import).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .database import connect

# Packaged with the backend rather than resolved through the repo layout, so it ships.
_STOCK_FILE = Path(__file__).with_name("stock-module-profiles.json")
_STOCK = {k: v for k, v in json.loads(_STOCK_FILE.read_text()).items() if not k.startswith("_")}

# What the "add profile" dropdown offers, in the order it should appear.
VARIANTS = [
    {"id": "TOUCH_WINDOWS", "label": "Touch", "moduleType": "TOUCH"},
    {"id": "TRACK_LEFT", "label": "Track (left)", "moduleType": "TRACK"},
    {"id": "TRACK_RIGHT", "label": "Track (right)", "moduleType": "TRACK"},
    {"id": "TUNE", "label": "Tune", "moduleType": "TUNE"},
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def variants() -> list[dict]:
    """The stock profiles a user can add, for the UI dropdown."""
    return [{**v, "bindings": len(_STOCK[v["id"]]["bindings"])} for v in VARIANTS if v["id"] in _STOCK]


def create(variant: str, name: str | None = None) -> dict:
    """Add a module profile seeded from its stock map."""
    stock = _STOCK.get(variant)
    if stock is None:
        raise ValueError(f"unknown variant {variant!r} (expected one of {sorted(_STOCK)})")
    now, cid = _now(), str(uuid.uuid4())
    conn = connect()
    try:
        # Number within the VARIANT, not the type: a second Track Left should be
        # "Naya Track Left 2", not "3" just because a Track Right also exists.
        base = stock["default_name"]
        taken = {r["name"] for r in conn.execute(
            "SELECT name FROM module_configs WHERE name = ? OR name LIKE ?", (base, base + " %"))}
        label = name or base
        if not name and label in taken:
            n = 2
            while f"{base} {n}" in taken:
                n += 1
            label = f"{base} {n}"
        conn.execute(
            "INSERT INTO module_configs (name, type, size, order_id, icon_id, id, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (label, stock["module_type"], 0, len(taken), None, cid, now, now),
        )
        for behavior, b in sorted(stock["bindings"].items()):
            conn.execute(
                "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                "invert, threshold, direction, mode, module_config_id, id, updated_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (None, b["action_code"], b["action_type"], behavior, 0, 0, "+", 0, cid,
                 str(uuid.uuid4()), now, now),
            )
        conn.commit()
        return {"ok": True, "id": cid, "name": label, "type": stock["module_type"],
                "bindings": len(stock["bindings"])}
    finally:
        conn.close()


def rename(config_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("a module profile needs a name")
    conn = connect()
    try:
        cur = conn.execute("UPDATE module_configs SET name=?, updated_at=? WHERE id=?",
                           (name, _now(), config_id))
        if cur.rowcount == 0:
            raise ValueError(f"no module profile {config_id}")
        conn.commit()
        return {"ok": True, "id": config_id, "name": name}
    finally:
        conn.close()


def delete(config_id: str) -> dict:
    """Remove a profile. Refuses the last one of its type: a module with no profile at all
    cannot be driven, and the device needs a config in the bay for the module to work."""
    conn = connect()
    try:
        row = conn.execute("SELECT type, name FROM module_configs WHERE id=?", (config_id,)).fetchone()
        if row is None:
            raise ValueError(f"no module profile {config_id}")
        n = conn.execute("SELECT COUNT(*) c FROM module_configs WHERE type=?", (row["type"],)).fetchone()["c"]
        if n <= 1:
            raise ValueError(
                f"{row['name']!r} is the only {row['type']} profile. A module with no profile "
                "cannot be driven -- add another before removing this one.")
        conn.execute("DELETE FROM module_bindings WHERE module_config_id=?", (config_id,))
        conn.execute("DELETE FROM module_settings WHERE module_config_id=?", (config_id,))
        conn.execute("DELETE FROM module_configs WHERE id=?", (config_id,))
        conn.commit()
        return {"ok": True, "id": config_id, "name": row["name"]}
    finally:
        conn.close()
