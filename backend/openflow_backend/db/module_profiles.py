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


def backfill_variants(conn) -> int:
    """Tag pre-existing rows with the variant they obviously are.

    Rows written before the `variant` column existed have none, so a new profile cannot be
    grouped beside them. The stock profiles are identifiable by their default name, so tag
    those; anything renamed beyond recognition keeps its position and simply is not grouped.
    """
    n = 0
    for key, stock in _STOCK.items():
        cur = conn.execute(
            "UPDATE module_configs SET variant=? WHERE variant IS NULL AND (name = ? OR name LIKE ?)",
            (key, stock["default_name"], f"Copy of {stock['default_name']} Defaults%"))
        n += cur.rowcount
    return n


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
        # A new profile is a copy of the stock map, so say so -- and number within the
        # VARIANT, not the type: a second Track Left must not be numbered because a Track
        # Right also exists.
        stock_name = stock["default_name"]
        base = f"Copy of {stock_name} Defaults"
        taken = {r["name"] for r in conn.execute(
            "SELECT name FROM module_configs WHERE name = ? OR name LIKE ?", (base, base + " %"))}
        label = name or base
        if not name and label in taken:
            n = 2
            while f"{base} {n}" in taken:
                n += 1
            label = f"{base} {n}"

        # Insert BELOW the profiles of the same variant, not at the top of the type. Track is
        # the case that matters: adding a right-hand profile should land under the existing
        # right-hand ones, not above "Naya Track Left". Variant is matched by name, which is
        # only reliable at creation time -- but order_id is written once and then stays, so a
        # later rename does not move anything (and should not).
        siblings = list(conn.execute(
            "SELECT id, name, order_id, variant FROM module_configs WHERE type=? ORDER BY order_id",
            (stock["module_type"],)))

        def is_variant(r):
            # Prefer the stored variant; fall back to the name only for rows written before the
            # column existed (a renamed legacy row simply appends at the end, which is safe).
            if r["variant"]:
                return r["variant"] == variant
            return r["name"] == stock_name or r["name"].startswith(f"Copy of {stock_name} Defaults")

        after = -1
        for i, r in enumerate(siblings):
            if is_variant(r):
                after = i
        pos = after + 1 if after >= 0 else len(siblings)   # end of the type if no sibling found
        for i, r in enumerate(siblings):
            if i >= pos:
                conn.execute("UPDATE module_configs SET order_id=? WHERE id=?", (i + 1, r["id"]))
            elif r["order_id"] != i:
                conn.execute("UPDATE module_configs SET order_id=? WHERE id=?", (i, r["id"]))
        conn.execute(
            "INSERT INTO module_configs (name, type, size, order_id, icon_id, variant, id, "
            "updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (label, stock["module_type"], 0, pos, None, variant, cid, now, now),
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


def capture_from_device(entries: list[dict]) -> list[dict]:
    """Give the board's own module state a profile of its own.

    A read used to leave drift implicit: the app kept an edited profile, the device kept
    something else, and the UI marked the edited one "on the keyboard" because it shared the
    device's uuid. That is a false claim, and it hides the board's real state entirely -- there
    was nowhere in the app to see what the keyboard was actually running.

    So a device config with no content-matching profile gets captured as one, the same way a
    layer whose uuid we do not recognise becomes a layer rather than being dropped. The user's
    edited profile is left exactly as it is, under its own name, no longer claiming to be live.

    The capture is a NEW row with a NEW uuid, deliberately: rewriting the id of a profile the
    user has been editing would repoint every bay that references it. The cost is that flashing
    a capture writes its new uuid into the slot, so the board's identity for that slot changes
    to the profile that was flashed -- which is the honest outcome.

    Only drifted configs whose TYPE we know are captured. A slot whose uuid matches nothing in
    the app has no discoverable type, so it is reported and left alone rather than guessed at.

    `entries` is the /rpc/read-modules module list. Returns one dict per captured profile.
    """
    todo = [e for e in entries
            if not e.get("unknown") and e.get("differs") and e.get("matched") is None]
    if not todo:
        return []

    now = _now()
    made = []
    conn = connect()
    try:
        for e in todo:
            cid = str(uuid.uuid4())
            # Name it after the profile it drifted from, so the pair reads as what it is.
            base = f"{e['name']} (on board)"
            taken = {r["name"] for r in conn.execute(
                "SELECT name FROM module_configs WHERE name = ? OR name LIKE ?",
                (base, base + " %"))}
            label = base
            if label in taken:
                n = 2
                while f"{base} {n}" in taken:
                    n += 1
                label = f"{base} {n}"

            # Sits directly below the profile it was captured from.
            src = conn.execute("SELECT order_id, variant FROM module_configs WHERE id=?",
                               (e["uuid"],)).fetchone()
            pos = (src["order_id"] + 1) if src else 0
            conn.execute("UPDATE module_configs SET order_id = order_id + 1 "
                         "WHERE type=? AND order_id >= ?", (e["type"], pos))
            conn.execute(
                "INSERT INTO module_configs (name, type, size, order_id, icon_id, variant, "
                "captured_from, id, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (label, e["type"], 0, pos, None, src["variant"] if src else None,
                 e["uuid"], cid, now, now))

            # What we KNOW plus what was READ -- not the read alone.
            #
            # The read only reports gestures with a device field we have mapped, which for a
            # Track is 4 of 11: capturing from it alone silently dropped vertical, horizontal
            # and rotate, and the new profile came out unable to express them at all. So the
            # capture starts as a copy of the profile it drifted from, and only the gestures
            # the device actually reported are overwritten.
            seen = {g["gesture"]: g.get("device") for g in (e.get("gestures") or [])}
            rows = {r["behavior"]: (r["action_code"], r["action_type"]) for r in conn.execute(
                "SELECT behavior, action_code, action_type FROM module_bindings "
                "WHERE module_config_id=?", (e["uuid"],))}
            for gesture, device in seen.items():
                rows[gesture] = (device or "", "keypress" if device else "none")
            for gesture, (code, atype) in sorted(rows.items()):
                conn.execute(
                    "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                    "invert, threshold, direction, mode, module_config_id, id, updated_at, "
                    "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (None, code or "", atype or "none", gesture, 0, 0, "+", 0,
                     cid, str(uuid.uuid4()), now, now))
            made.append({"id": cid, "name": label, "type": e["type"],
                         "capturedFrom": e["uuid"], "slot": e["slot"]})
        conn.commit()
        return made
    finally:
        conn.close()


def repoint_bays(pairs, profile_id) -> int:
    """Move bays from a profile that is no longer live onto the one that is.

    A bay names the profile a layer RUNS. When a read finds the board running something other
    than the profile a bay points at, leaving the bay alone would show one profile as live in
    the UI while a flash quietly wrote a different one. The profile being moved away from is
    untouched and can be selected again deliberately.

    Scoped to ONE profile, and that matters: only the profile representing the board should
    follow it. Another profile's bays are a deliberate choice about what to flash NEXT, and
    rewriting those on every read silently threw the user's selections away.

    `pairs` is [(from config id, to config id)]. Returns the number of bays moved.
    """
    pairs = [(a, b) for a, b in pairs if a and b and a != b]
    if not pairs or not profile_id:
        return 0
    now, moved = _now(), 0
    conn = connect()
    try:
        for src, dst in pairs:
            moved += conn.execute(
                "UPDATE module_config_bindings SET module_config_id=?, updated_at=? "
                "WHERE module_config_id=? AND profile_id=?",
                (dst, now, src, profile_id)).rowcount
            # Provenance is a fact about the profile, not about any one profile's bays, so it
            # is recorded whatever the scope. Captures made before this column existed have
            # none, and without it a flash allocates a fresh slot and strands the original.
            conn.execute(
                "UPDATE module_configs SET captured_from=? "
                "WHERE id=? AND (captured_from IS NULL OR captured_from='')", (src, dst))
        conn.commit()
        return moved
    finally:
        conn.close()
