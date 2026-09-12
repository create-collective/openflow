"""NayaFlow user-data.db  <->  OpenFlow profile JSON, without touching anyone's live database.

The core behind tools/nayaflow_db_convert.py and the "Load profile from file" route, which
accepts a NayaFlow database directly: `to_json_payloads` reads a database into a THROWAWAY
copy, translates the beta-era forms into OpenFlow's, and returns the app's own profile payloads
(`kind: "profile"`, one per profile, importable as a NEW profile beside the user's own);
`to_db` writes an edited payload back into a copy of the ORIGINAL FILE, which keeps that
file's schema byte for byte, with the beta forms restored from the stash the export carries.

WHAT THE BETA SCHEMA DOES DIFFERENTLY (measured on another owner's file, 2026-09-11):
  * module_settings rows are keyed `MS-n`, not by the field id. The numbering follows the
    settings schema per module type: Touch MS-2..5, Track MS-7..10, Tune MS-11..17, each in the
    order scroll speed, pointer speed, acceleration, acceleration on (+ the Tune's three tick
    fields). Best evidence, not a capture: unmapped ids are carried through untouched.
  * A split Track axis is stored as separate per-direction rows -- track_up / track_down /
    track_left / track_right / clockwise_rotate / counter_clockwise_rotate -- where OpenFlow
    and NayaFlow 1.25.1 store one axis row plus a per-half row with a direction column.
  * The stock Track axes carry invert=1. OpenFlow implements invert for real (it flips the
    selector signs at flash), so the flag is cleared on the way out, stashed, and restored.
  * layers has no animation column and no module colour columns; keys has 97 colours per layer.

Only module configs a bay references travel with a profile (that is what the app's own export
carries). Nothing here writes to any path but the one the caller names.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import database as dbm
from . import profiles as prof

# --- the beta forms ------------------------------------------------------------------------

_ORDER = ["scroll_speed", "pointer_speed", "pointer_accel", "pointer_accel_on"]
_TUNE_EXTRA = ["ticks_per_rotation", "tick_strength", "toggle_ticks"]
BETA_SETTING_IDS = {
    "TOUCH": {f"MS-{2 + i}": sid for i, sid in enumerate(_ORDER)},
    "TRACK": {f"MS-{7 + i}": sid for i, sid in enumerate(_ORDER)},
    "TUNE": {f"MS-{11 + i}": sid for i, sid in enumerate(_ORDER + _TUNE_EXTRA)},
}
BETA_SETTING_IDS_REV = {t: {v: k for k, v in m.items()} for t, m in BETA_SETTING_IDS.items()}

# per-direction beta row -> (axis behavior, half)
BETA_HALVES = {
    "track_up:track": ("vertical:track", "-"), "track_down:track": ("vertical:track", "+"),
    "track_left:track": ("horizontal:track", "-"), "track_right:track": ("horizontal:track", "+"),
    "counter_clockwise_rotate:track": ("rotate:track", "-"), "clockwise_rotate:track": ("rotate:track", "+"),
}
BETA_HALVES_REV = {v: k for k, v in BETA_HALVES.items()}
AXIS_DEFAULTS = {
    "vertical:track": "mouse - MOUSE_DOWN - MOUSE_UP",
    "horizontal:track": "mouse - MOUSE_LEFT - MOUSE_RIGHT",
    "rotate:track": "mouse - SCROLL_UP - SCROLL_DOWN",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _uid() -> str:
    return str(uuid.uuid4())


def _row_conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _insert(conn, table, row: dict) -> None:
    """INSERT only the columns this schema has; timestamps filled when present."""
    cols = _columns(conn, table)
    data = {k: v for k, v in row.items() if k in cols}
    for ts in ("updated_at", "created_at"):
        if ts in cols and ts not in data:
            data[ts] = _now()
    keys = list(data)
    conn.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
                 [data[k] for k in keys])


# --- to-json -------------------------------------------------------------------------------

def _normalise_beta(conn) -> dict:
    """Rewrite the beta forms in a THROWAWAY copy into OpenFlow's. Returns what was stashed."""
    stash: dict = {"settings": {}, "invert": {}, "halves": {}, "synthesized": {}}
    types = {r["id"]: (r["type"] or "").upper() for r in conn.execute("SELECT id, type FROM module_configs")}

    # 1. MS-n settings -> named ids
    for r in conn.execute("SELECT rowid, module_config_id, correlation_id, value FROM module_settings").fetchall():
        m = BETA_SETTING_IDS.get(types.get(r["module_config_id"], ""), {})
        if r["correlation_id"] in m:
            stash["settings"].setdefault(r["module_config_id"], {})[m[r["correlation_id"]]] = r["correlation_id"]
            val = r["value"]
            if m[r["correlation_id"]] in ("pointer_accel_on", "toggle_ticks"):
                val = "true" if str(val).lower() in ("on", "true", "1") else "false"
            conn.execute("UPDATE module_settings SET correlation_id=?, value=? WHERE rowid=?",
                         (m[r["correlation_id"]], val, r["rowid"]))

    # 2. per-direction Track rows -> axis row + half rows
    rows = conn.execute("SELECT rowid, module_config_id, behavior, action_code, action_type, direction, invert "
                        "FROM module_bindings").fetchall()
    for r in rows:
        beh = r["behavior"] or ""
        if beh in BETA_HALVES:
            axis, half = BETA_HALVES[beh]
            cid = r["module_config_id"]
            stash["halves"].setdefault(cid, []).append(beh)
            if r["action_code"]:
                conn.execute("UPDATE module_bindings SET behavior=?, direction=? WHERE rowid=?",
                             (axis, half, r["rowid"]))
            else:
                conn.execute("DELETE FROM module_bindings WHERE rowid=?", (r["rowid"],))
            has_axis = conn.execute("SELECT 1 FROM module_bindings WHERE module_config_id=? AND behavior=? "
                                    "AND (direction IS NULL OR direction='+') AND action_type='value'",
                                    (cid, axis)).fetchone()
            if has_axis is None and r["action_code"]:
                # OpenFlow shows a split axis as the axis row plus its halves; the beta had no
                # axis row here, so remember that this one is ours and drop it on the way back.
                stash["synthesized"].setdefault(cid, []).append(axis)
                _insert(conn, "module_bindings", {"action_code": AXIS_DEFAULTS[axis], "action_type": "value",
                                                  "behavior": axis, "invert": 0, "threshold": 0,
                                                  "direction": "+", "mode": 0, "module_config_id": cid,
                                                  "id": _uid()})

    # 3. invert flags: stash and clear
    for r in conn.execute("SELECT rowid, module_config_id, behavior, invert FROM module_bindings WHERE invert=1").fetchall():
        stash["invert"].setdefault(r["module_config_id"], []).append(r["behavior"])
        conn.execute("UPDATE module_bindings SET invert=0 WHERE rowid=?", (r["rowid"],))
    conn.commit()
    return stash


def to_json_payloads(db: Path) -> list[dict]:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "copy.db"
        shutil.copyfile(db, tmp)
        # OpenFlow's additive columns, so the app's own export queries run on an older file.
        dbm.init_db(tmp)
        conn = _row_conn(tmp)
        try:
            goose = [r[0] for r in conn.execute("SELECT version_id FROM goose_db_version ORDER BY version_id")] \
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='goose_db_version'").fetchone() else []
            names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM module_configs")}
            stash = _normalise_beta(conn)
            payloads = []
            pids = [r["id"] for r in conn.execute("SELECT id FROM profiles ORDER BY order_id")]
            for i, pid in enumerate(pids):
                payload = prof._profile_payload(conn, pid)
                # Re-apply invert onto the LIVE binding entries. _normalise_beta cleared it from
                # the working copy (so the metadata stash below is the exact round-trip record),
                # but OpenFlow's own flash reads `invert` off these entries and flips the selector
                # signs -- clearing it here silently dropped the owner's inversion on every import.
                # Stashed by module_config_id -> [behavior]; entries carry srcId + behavior.
                for cfg in payload.get("modules", {}).get("configs", []):
                    inv = set(stash["invert"].get(cfg.get("srcId"), []))
                    if inv:
                        for b in cfg.get("bindings", []):
                            if b.get("behavior") in inv:
                                b["invert"] = 1
                payload["nayaflowSource"] = {
                    "file": db.name, "gooseVersions": goose, "profileId": pid,
                    "beta": {"settingsIds": {names.get(k, k): v for k, v in stash["settings"].items()},
                             "invert": {names.get(k, k): v for k, v in stash["invert"].items()},
                             "perDirectionRows": {names.get(k, k): v for k, v in stash["halves"].items()},
                             "synthesizedAxes": {names.get(k, k): v for k, v in stash["synthesized"].items()}},
                    "note": "importable with OpenFlow's Import profile; the beta forms are stashed here "
                            "and put back by `to-db --template`",
                }
                payloads.append(payload)
            return payloads
        finally:
            conn.close()


def to_json(db: Path, out: Path) -> list[Path]:
    """The payloads as files: `out` for one profile, `out-<n>` each for several."""
    payloads = to_json_payloads(db)
    written = []
    for i, payload in enumerate(payloads):
        dest = out if len(payloads) == 1 else out.with_name(f"{out.stem}-{i}{out.suffix}")
        dest.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(dest)
    return written


def to_db_payload(data: dict, template: Path, out: Path) -> dict:
    """`to_db` for an already-parsed payload."""
    return _to_db(data, template, out)


# --- to-db ---------------------------------------------------------------------------------

def to_db(src: Path, template: Path, out: Path) -> dict:
    return _to_db(json.loads(src.read_text(encoding="utf-8")), template, out)


def _to_db(data: dict, template: Path, out: Path) -> dict:
    if data.get("kind") != "profile":
        raise ValueError("not a profile export")
    beta = (data.get("nayaflowSource") or {}).get("beta") or {}
    shutil.copyfile(template, out)
    conn = _row_conn(out)
    try:
        now = _now()
        pname = data["profile"]["name"]
        # Replace the profile of the same name, and every module config the payload carries, by name.
        old = conn.execute("SELECT id FROM profiles WHERE name=?", (pname,)).fetchone()
        if old:
            for lid, in conn.execute("SELECT id FROM layers WHERE profile_id=?", (old["id"],)).fetchall():
                conn.execute("DELETE FROM key_bindings WHERE key_id IN (SELECT id FROM keys WHERE layer_id=?)", (lid,))
                conn.execute("DELETE FROM keys WHERE layer_id=?", (lid,))
            conn.execute("DELETE FROM module_config_bindings WHERE profile_id=?", (old["id"],))
            conn.execute("DELETE FROM layers WHERE profile_id=?", (old["id"],))
            conn.execute("DELETE FROM profiles WHERE id=?", (old["id"],))
        for c in (data.get("modules") or {}).get("configs", []):
            for cid, in conn.execute("SELECT id FROM module_configs WHERE name=? AND type=?", (c["name"], c["type"])).fetchall():
                conn.execute("DELETE FROM module_bindings WHERE module_config_id=?", (cid,))
                conn.execute("DELETE FROM module_settings WHERE module_config_id=?", (cid,))
                conn.execute("DELETE FROM module_config_bindings WHERE module_config_id=?", (cid,))
                conn.execute("DELETE FROM module_configs WHERE id=?", (cid,))

        pid = _uid()
        order = conn.execute("SELECT COALESCE(MAX(order_id), -1) + 1 FROM profiles").fetchone()[0]
        _insert(conn, "profiles", {"name": pname, "order_id": order, "state": "ON_BOARD",
                                   "icon_id": data["profile"].get("iconId"), "id": pid})
        layer_map = {}
        for l in data.get("layers", []):
            lid = _uid()
            layer_map[l.get("srcId")] = lid
            _insert(conn, "layers", {"name": l["name"], "order_id": l.get("orderId", 0), "icon_id": l.get("iconId"),
                                     "profile_id": pid, "id": lid, "animation_id": l.get("animationId")})
            have = set()
            for k in l.get("keys", []):
                kid = _uid()
                have.add(k["positionId"])
                _insert(conn, "keys", {"color_hex": k.get("colorHex"), "position_id": k["positionId"],
                                       "layer_id": lid, "id": kid})
                for b in k.get("bindings", []):
                    _insert(conn, "key_bindings", {"context": b.get("context"), "action_code": b.get("actionCode"),
                                                   "action_type": b.get("actionType"), "behavior": b.get("behavior"),
                                                   "key_id": kid, "id": _uid()})
            # NayaFlow keeps a row for every one of the 97 positions; keep that invariant.
            for pos in range(97):
                if pos not in have:
                    _insert(conn, "keys", {"color_hex": None, "position_id": pos, "layer_id": lid, "id": _uid()})

        cmap = {}
        for c in (data.get("modules") or {}).get("configs", []):
            cid = _uid()
            cmap[c["srcId"]] = cid
            _insert(conn, "module_configs", {"name": c["name"], "order_id": c.get("orderId", 0), "icon_id": c.get("iconId"),
                                             "description": c.get("description"), "size": c.get("size", 0),
                                             "type": c["type"], "id": cid})
            inv = set((beta.get("invert") or {}).get(c["name"], []))
            per_dir = set((beta.get("perDirectionRows") or {}).get(c["name"], []))
            synth = set((beta.get("synthesizedAxes") or {}).get(c["name"], []))
            for b in c.get("bindings", []):
                beh, direction = b["behavior"], b.get("direction") or "+"
                code, atype = b.get("action_code"), b.get("action_type")
                if beh in synth and atype == "value" and direction == "+":
                    continue                       # the axis row to-json added; the beta has none
                # a half row of a split axis -> the beta's per-direction row, if this config used them
                if (beh, direction) in BETA_HALVES_REV and atype != "value" and per_dir:
                    beh, direction = BETA_HALVES_REV[(beh, direction)], "+"
                _insert(conn, "module_bindings", {"action_id": b.get("action_id"), "action_code": code,
                                                  "action_type": atype, "behavior": beh,
                                                  "invert": 1 if beh in inv else b.get("invert", 0),
                                                  "threshold": b.get("threshold", 0), "direction": direction,
                                                  "mode": b.get("mode", 0), "module_config_id": cid, "id": _uid()})
            # the beta wrote an (empty) row for every per-direction gesture it knew
            present = {b["behavior"] for b in c.get("bindings", [])}
            for beh in per_dir:
                if beh not in present and BETA_HALVES[beh] not in {(b["behavior"], b.get("direction") or "+") for b in c.get("bindings", [])}:
                    _insert(conn, "module_bindings", {"action_code": None, "action_type": None, "behavior": beh,
                                                      "invert": 0, "threshold": 0, "direction": "+", "mode": 0,
                                                      "module_config_id": cid, "id": _uid()})
            ids_back = (beta.get("settingsIds") or {}).get(c["name"], {})
            rev = BETA_SETTING_IDS_REV.get((c["type"] or "").upper(), {})
            for s in c.get("settings", []):
                sid = s["correlation_id"]
                back = ids_back.get(sid) or (rev.get(sid) if sid in rev and ids_back else None) or sid
                val = s["value"]
                if back.startswith("MS-") and sid in ("pointer_accel_on", "toggle_ticks"):
                    val = "on" if str(val).lower() in ("true", "on", "1") else "off"
                _insert(conn, "module_settings", {"value": val, "type": s.get("type", "string"),
                                                  "correlation_id": back, "module_config_id": cid})
        for mcb in (data.get("modules") or {}).get("configBindings", []):
            lid = layer_map.get(mcb["srcLayerId"])
            if lid is None:
                continue
            _insert(conn, "module_config_bindings", {"profile_id": pid, "layer_id": lid,
                                                     "module_config_id": cmap.get(mcb["srcConfigId"], mcb["srcConfigId"]),
                                                     "binding_location": mcb["bindingLocation"], "state": mcb.get("state")})
        conn.commit()
        return {"ok": True, "profile": pname, "profileId": pid, "modules": len(cmap), "out": str(out)}
    finally:
        conn.close()


# --- roundtrip check ------------------------------------------------------------------------

def _shape(db: Path) -> dict:
    """Everything that matters, with ids and timestamps stripped, so two files can be compared."""
    conn = _row_conn(db)
    try:
        out: dict = {}
        prof_by_id = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM profiles")}
        layers = {r["id"]: (prof_by_id.get(r["profile_id"]), r["order_id"], r["name"])
                  for r in conn.execute("SELECT id, profile_id, order_id, name FROM layers")}
        keys = {}
        for r in conn.execute("SELECT id, layer_id, position_id, color_hex FROM keys"):
            keys[r["id"]] = (layers.get(r["layer_id"]), r["position_id"])
            out.setdefault("colours", {})[str((layers.get(r["layer_id"]), r["position_id"]))] = r["color_hex"]
        out["bindings"] = sorted(
            f"{keys.get(r['key_id'])} {r['behavior']} {r['action_type']} {r['action_code']} {r['context']}"
            for r in conn.execute("SELECT key_id, behavior, action_type, action_code, context FROM key_bindings"))
        cfg = {r["id"]: (r["name"], r["type"]) for r in conn.execute("SELECT id, name, type FROM module_configs")}
        out["module_bindings"] = sorted(
            f"{cfg.get(r['module_config_id'])} {r['behavior']} {r['direction']} {r['action_type']} {r['action_code']} inv={r['invert']}"
            for r in conn.execute("SELECT module_config_id, behavior, direction, action_type, action_code, invert FROM module_bindings"))
        out["module_settings"] = sorted(
            f"{cfg.get(r['module_config_id'])} {r['correlation_id']}={r['value']}"
            for r in conn.execute("SELECT module_config_id, correlation_id, value FROM module_settings"))
        out["bays"] = sorted(
            f"{layers.get(r['layer_id'])} {r['binding_location']} {cfg.get(r['module_config_id'])} {r['state']}"
            for r in conn.execute("SELECT layer_id, binding_location, module_config_id, state FROM module_config_bindings"))
        out["schema"] = {t: _columns(conn, t) for t in ("profiles", "layers", "keys", "key_bindings",
                                                        "module_configs", "module_bindings", "module_settings")}
        return out
    finally:
        conn.close()


def roundtrip(db: Path) -> dict:
    with tempfile.TemporaryDirectory() as td:
        j = Path(td) / "p.json"
        back = Path(td) / "back.db"
        to_json(db, j)
        to_db(j, db, back)
        a, b = _shape(db), _shape(back)
        diffs = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
        return {"identical": not diffs, "differences": list(diffs)}


