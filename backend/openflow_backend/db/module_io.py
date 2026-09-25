"""Export and import a module profile as JSON.

The interchange format is deliberately NOT the database rows. Two things make the raw rows a
bad thing to hand someone:

* a split axis is three rows -- the combined one plus a half per direction, two of which share
  direction "+" -- so a flat list reads as duplicates and invites the reader to "fix" it;
* `module_config_id`, row ids and timestamps are meaningless outside this machine.

So a binding is one entry keyed by its gesture, with the halves nested under `split` where they
exist. That is also how the UI thinks about it, which means a file is readable by someone who
has only ever seen the Modules page.

`moduleType` is required and comes first: it decides which section of the module list the
profile lands in, and there is no way to infer it from the gestures alone that would not
silently misfile a hand-written file. An import that cannot name its type is refused rather
than guessed at.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..device import module_fields
from .database import connect

FORMAT = "openflow.module-profile"
VERSION = 1
TYPES = ("TOUCH", "TRACK", "TUNE", "FLOAT")


class ProfileFormatError(ValueError):
    """The document is not a module profile we can import."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def export_profile(config_id: str) -> dict:
    """One module profile as a portable document."""
    conn = connect()
    try:
        cfg = conn.execute(
            "SELECT id, name, type, variant FROM module_configs WHERE id=?", (config_id,)).fetchone()
        if cfg is None:
            raise ProfileFormatError(f"no module profile {config_id}")

        halves = module_fields.axis_halves(cfg["type"])
        bindings: dict = {}
        for r in conn.execute(
                "SELECT behavior, action_type, action_code, direction, invert, threshold, mode "
                "FROM module_bindings WHERE module_config_id=? ORDER BY behavior, direction",
                (config_id,)):
            beh, code = r["behavior"], r["action_code"] or ""
            entry = bindings.setdefault(beh, {"actionType": "none", "actionCode": ""})
            # A per-half row of a split axis: nested, not a sibling. Whether a row is a half is
            # decided by the field map, not by the presence of a direction -- every ordinary
            # row carries "+" too.
            if beh in halves and code and " - " not in code and r["direction"] in ("-", "+"):
                entry.setdefault("split", {})[r["direction"]] = {
                    "actionType": r["action_type"] or "none", "actionCode": code}
                continue
            entry["actionType"] = r["action_type"] or "none"
            entry["actionCode"] = code
            if r["invert"]:
                entry["invert"] = True
            if r["threshold"]:
                entry["threshold"] = r["threshold"]
            if r["mode"]:
                entry["mode"] = r["mode"]

        settings = {s["correlation_id"]: s["value"] for s in conn.execute(
            "SELECT correlation_id, value FROM module_settings WHERE module_config_id=?",
            (config_id,))}

        doc = {
            "format": FORMAT,
            "version": VERSION,
            "moduleType": cfg["type"],          # required, and first: it decides where this lands
            "name": cfg["name"],
            "bindings": dict(sorted(bindings.items())),
        }
        if cfg["variant"]:
            doc["variant"] = cfg["variant"]
        if settings:
            doc["settings"] = settings
        return doc
    finally:
        conn.close()


def _validate(doc) -> tuple[str, str, dict]:
    if not isinstance(doc, dict):
        raise ProfileFormatError("a module profile must be a JSON object")
    fmt = doc.get("format")
    if fmt and fmt != FORMAT:
        raise ProfileFormatError(f"{fmt!r} is not a module profile (expected {FORMAT!r})")
    mtype = str(doc.get("moduleType") or "").upper()
    if not mtype:
        raise ProfileFormatError(
            "moduleType is required -- it decides which module this profile belongs to, and "
            f"guessing it from the gestures would misfile the file. Expected one of {', '.join(TYPES)}.")
    if mtype not in TYPES:
        raise ProfileFormatError(f"unknown moduleType {doc.get('moduleType')!r} (expected one of {', '.join(TYPES)})")
    bindings = doc.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ProfileFormatError("bindings must be a non-empty object keyed by gesture")

    known = set(module_fields.field_map(mtype).get(k, {}).get("gesture")
                for k in module_fields.field_map(mtype))
    known |= set(module_fields.axis_halves(mtype))
    known |= set(module_fields.paired_gestures(mtype))
    known.discard(None)
    unknown = [g for g in bindings if g not in known]
    if unknown and len(unknown) == len(bindings):
        raise ProfileFormatError(
            f"none of these gestures belong to a {mtype} module -- is moduleType right? "
            f"(saw {', '.join(sorted(unknown)[:3])})")
    return mtype, str(doc.get("name") or f"Imported {mtype.title()}"), bindings


# The stock map an import starts from, per type: what "add profile" seeds a new one with
# (module_profiles.create). A Track picks its side from the file's variant.
_SEED_VARIANT = {"TUNE": "TUNE", "TOUCH": "TOUCH_WINDOWS", "TRACK": "TRACK_LEFT"}


def _seed(mtype: str, variant: str | None) -> dict:
    """{gesture: (action_type, action_code)} of the stock map this import starts from."""
    from . import module_profiles
    stock = module_profiles._STOCK.get(variant or "") or module_profiles._STOCK.get(
        _SEED_VARIANT.get(mtype, ""))
    if not stock or stock["module_type"] != mtype:
        return {}
    return {g: (b["action_type"], b["action_code"]) for g, b in stock["bindings"].items()}


def import_profile(doc: dict, name: str | None = None) -> dict:
    """Create a module profile from a document. Never overwrites: an import is always a new
    profile, so importing a file twice gives you two you can compare rather than a surprise.

    A file need not name every gesture -- Create Companion's names only the ones it binds. The
    profile starts from the type's stock map, as a new profile does, and the file's bindings
    replace those gestures. Until 2026-09-25 only the file's gestures were created, so an
    imported Tune showed seven rows where the module has seventeen."""
    mtype, doc_name, bindings = _validate(doc)
    label = (name or doc_name).strip() or f"Imported {mtype.title()}"
    now, cid = _now(), str(uuid.uuid4())

    conn = connect()
    try:
        taken = {r["name"] for r in conn.execute(
            "SELECT name FROM module_configs WHERE name = ? OR name LIKE ?", (label, label + " %"))}
        if label in taken:
            n = 2
            while f"{label} {n}" in taken:
                n += 1
            label = f"{label} {n}"

        pos = conn.execute("SELECT COUNT(*) c FROM module_configs WHERE type=?",
                           (mtype,)).fetchone()["c"]
        variant = doc.get("variant")
        conn.execute(
            "INSERT INTO module_configs (name, type, size, order_id, icon_id, variant, id, "
            "updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (label, mtype, 0, pos, None, variant, cid, now, now))

        def add(gesture, code, atype, direction, entry, invert=False):
            conn.execute(
                "INSERT INTO module_bindings (action_id, action_code, action_type, behavior, "
                "invert, threshold, direction, mode, module_config_id, id, updated_at, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (None, code or "", atype or "none", gesture, 1 if invert else 0,
                 int(entry.get("threshold") or 0), direction, int(entry.get("mode") or 0),
                 cid, str(uuid.uuid4()), now, now))

        # A split on a PAIRED gesture (the Tune dial) names the pair's own half gestures, not
        # direction rows under the combined one. Stored as rows of the combined gesture they
        # were three rows for one behaviour, and the flash keeps one value per behaviour --
        # whichever row came last, sometimes the bare "F23" instead of the pair.
        pairs = module_fields.paired_gestures(mtype)
        written = {g for g, e in bindings.items() if isinstance(e, dict)}
        for gesture, entry in bindings.items():
            for half in (pairs.get(gesture) or {}).values():
                written.add(half)

        rows, skipped = 0, []
        for gesture, (atype, code) in sorted(_seed(mtype, variant).items()):
            if gesture not in written:
                add(gesture, code, atype, "+", {})
                rows += 1
        for gesture, entry in bindings.items():
            if not isinstance(entry, dict):
                skipped.append(gesture)
                continue
            add(gesture, entry.get("actionCode"), entry.get("actionType"), "+", entry,
                bool(entry.get("invert")))
            rows += 1
            for sign, half in (entry.get("split") or {}).items():
                if sign in ("-", "+") and isinstance(half, dict):
                    target = (pairs.get(gesture) or {}).get(sign)
                    if target:
                        add(target, half.get("actionCode"), half.get("actionType"), "+", entry)
                    else:
                        add(gesture, half.get("actionCode"), half.get("actionType"), sign, entry)
                    rows += 1

        for cor, val in (doc.get("settings") or {}).items():
            conn.execute("INSERT INTO module_settings (module_config_id, correlation_id, value) "
                         "VALUES (?,?,?)", (cid, str(cor), str(val)))
        conn.commit()
        return {"ok": True, "id": cid, "name": label, "type": mtype,
                "bindings": rows, "skipped": skipped}
    finally:
        conn.close()
