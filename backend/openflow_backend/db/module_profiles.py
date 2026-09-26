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
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..device import module_fields
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

        # A bay names the profile a layer RUNS, and module_config_bindings has a foreign key
        # onto this row. Deleting underneath it raised IntegrityError, which is not a
        # ValueError, so it escaped the endpoint's handler as an unhandled 500 -- and uvicorn
        # drops the connection on those, which the browser reports as "failed to fetch". Say
        # what is actually in the way instead, naming the layers so it can be acted on.
        used = list(conn.execute(
            "SELECT p.name AS profile, l.order_id AS ord, l.name AS layer "
            "FROM module_config_bindings b "
            "LEFT JOIN profiles p ON p.id = b.profile_id "
            "LEFT JOIN layers l ON l.id = b.layer_id "
            "WHERE b.module_config_id = ? ORDER BY p.name, l.order_id", (config_id,)))
        if used:
            def _where(u):
                layer = u["layer"] or "layer %s" % u["ord"]
                return "%s / %s" % (u["profile"] or "a keymap profile", layer)
            where = sorted({_where(u) for u in used})
            raise ValueError(
                f"{row['name']!r} is still assigned to a module bay on "
                + ", ".join(where)
                + ". Point those layers at another profile first -- deleting it here would "
                  "silently change what those layers run.")

        conn.execute("DELETE FROM module_bindings WHERE module_config_id=?", (config_id,))
        conn.execute("DELETE FROM module_settings WHERE module_config_id=?", (config_id,))
        conn.execute("DELETE FROM module_configs WHERE id=?", (config_id,))
        conn.commit()
        return {"ok": True, "id": config_id, "name": row["name"]}
    finally:
        conn.close()


# A capture's own suffix, " (on board)" or " (on board) 3", stripped before naming a copy of it.
_ON_BOARD = re.compile(r"(?: \(on board\)(?: \d+)?)+$")


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

    A slot whose uuid the app has never seen is captured too, since 2026-09-09. Its type comes
    from the module list (each entry's third byte), and the capture starts from the CLOSEST
    profile of that type -- `templateId`, chosen by the read -- rather than from the profile
    sharing its uuid, because there is none. Only a slot the list gives no recognisable type for
    is still reported as unknown and left alone.

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
            # Name it after the profile it drifted from, so the pair reads as what it is. A copy
            # taken from a copy counts on from the original ("X (on board) 2"), never
            # "X (on board) (on board)" (owner's call, 2026-09-26).
            base = f"{_ON_BOARD.sub('', e['name'])} (on board)"
            taken = {r["name"] for r in conn.execute(
                "SELECT name FROM module_configs WHERE name = ? OR name LIKE ?",
                (base, base + " %"))}
            label = base
            if label in taken:
                n = 2
                while f"{base} {n}" in taken:
                    n += 1
                label = f"{base} {n}"

            # The profile this capture starts from: the one sharing the slot's uuid, or for a
            # uuid the app has never seen, the closest profile of its type (the read picks it).
            # `captured_from` below still records the DEVICE uuid, which is what a later flash
            # uses to claim this slot rather than allocating a fresh one.
            tmpl = e.get("templateId") or e["uuid"]
            # Sits directly below the profile it was captured from.
            src = conn.execute("SELECT order_id, variant FROM module_configs WHERE id=?",
                               (tmpl,)).fetchone()
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
            # Rows are keyed by (gesture, DIRECTION), not by gesture alone. An axis is two
            # fields and a split binds them independently, so a capture keyed on the behavior
            # collapsed all three rows -- the combined one and both halves -- into whichever
            # came last, and then wrote it back with a hardcoded "+". The captured profile
            # showed the plus half twice and lost the minus half entirely, which made it look
            # like the flash had not written the left/up directions when in fact the capture
            # could not represent them.
            rows = {(r["behavior"], r["direction"] or "+"):
                    (r["action_code"], r["action_type"]) for r in conn.execute(
                "SELECT behavior, action_code, action_type, direction FROM module_bindings "
                "WHERE module_config_id=?", (tmpl,))}

            halves = module_fields.axis_halves(e["type"])
            seen, axis_seen = {}, {}
            for g in (e.get("gestures") or []):
                if g["gesture"] in halves and g.get("half"):
                    axis_seen[(g["gesture"], g["half"])] = g.get("device")
                else:
                    seen[(g["gesture"], g.get("half") or "+")] = g.get("device")
            for key, device in seen.items():
                rows[key] = (device or "", "keypress" if device else "none")

            # An axis is stored the way the app stores it, not as two loose halves: a COMBINED
            # row naming the pair, plus per-half rows only when a half has actually been split
            # off onto something else. Writing halves unconditionally would make every capture
            # look split, and -- because get_modules() hides half rows and renders the combined
            # one -- an axis with no combined row disappears from the UI entirely.
            # A split axis is THREE rows in the app -- the combined one and both halves -- and
            # two of them share direction "+", so the axis rows are built as a list rather than
            # keyed like the rest.
            extra = []
            for gesture, h in halves.items():
                if not any(k[0] == gesture for k in axis_seen):
                    continue                      # the read said nothing about this axis
                rows.pop((gesture, "-"), None)
                rows.pop((gesture, "+"), None)
                names = [x.strip() for x in h["default"].split(" - ")][1:]
                got = [axis_seen.get((gesture, sign)) for sign in ("-", "+")]
                if got == names:
                    # Stock motion in both halves: one combined row, exactly as the app writes
                    # an unsplit axis.
                    extra.append((gesture, "+", h["default"], "value"))
                    continue
                # Anything else -- a half split onto a key, an inverted selector, or a field
                # the board leaves EMPTY -- is recorded as it is. Writing the default pair here
                # claimed a motion the keyboard does not have: the Touch slot really does hold
                # nothing for 1-finger pointer motion, and a capture that said MOUSE_LEFT could
                # never match the board it was taken from.
                extra.append((gesture, "+", "", "none"))
                for sign, code in zip(("-", "+"), got):
                    if code:
                        extra.append((gesture, sign, code, "key"))
            # The slot's setting values (speeds, acceleration, tick feedback) come along too.
            # Until 2026-09-11 a capture carried none, so it flashed back with the fields
            # templated from the board -- right by accident -- while the Settings tab showed the
            # app's defaults rather than what the keyboard runs.
            for srow in (e.get("settings") or []):
                dev = srow.get("device")
                if dev is None:
                    continue
                val = "true" if dev is True else "false" if dev is False else str(int(dev))
                conn.execute(
                    "INSERT INTO module_settings (value, type, correlation_id, module_config_id, "
                    "updated_at, created_at) VALUES (?,?,?,?,?,?)",
                    (val, "device", srow["id"], cid, now, now))
            # The capture's gesture names were decoded under the TEMPLATE's scroll direction
            # convention (each candidate is compared under its own), so the capture carries
            # that convention too, or its names would mean the other way round (SCRUM-62).
            conv = conn.execute(
                "SELECT value FROM module_settings WHERE module_config_id=? AND correlation_id=?",
                (tmpl, module_fields.SCROLL_CONVENTION_ID)).fetchone()
            if conv is not None and conv[0]:
                conn.execute(
                    "INSERT INTO module_settings (value, type, correlation_id, module_config_id, "
                    "updated_at, created_at) VALUES (?,?,?,?,?,?)",
                    (conv[0], "app", module_fields.SCROLL_CONVENTION_ID, cid, now, now))
            flat = [(g, d, c, t) for (g, d), (c, t) in rows.items()] + extra
            for gesture, direction, code, atype in sorted(flat):
                conn.execute(
                    "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                    "invert, threshold, direction, mode, module_config_id, id, updated_at, "
                    "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (None, code or "", atype or "none", gesture, 0, 0, direction, 0,
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

# The behaviors the old "pinch and spread are one gesture" model invented. They pointed at no
# device field (flashable False), so nothing was ever written through them; the pinch axis
# replaced them on 2026-09-18. See tests/test_pinch_spread.py.
_RETIRED_PINCH = ("pinch:touch:2_fingers", "pinch:tune:2_fingers")


def drop_retired_pinch_rows(conn) -> int:
    """Delete the unbound leftovers of the old pinch model; return how many went.

    A BOUND row is left alone. It is the user's binding, it was never reaching the keyboard
    anyway, and deleting it to tidy a data model is not a trade a migration gets to make.

    Tolerates a database with no module_bindings at all: this runs from init_db, which also runs
    over an imported NayaFlow or beta database that predates the table.
    """
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='module_bindings'"
    ).fetchone()
    if has_table is None:
        return 0
    placeholders = ",".join("?" for _ in _RETIRED_PINCH)
    cur = conn.execute(
        "DELETE FROM module_bindings WHERE behavior IN (" + placeholders + ") "
        "AND (action_code IS NULL OR action_code = '')", _RETIRED_PINCH)
    return cur.rowcount or 0
