"""tools/nayaflow_db_convert.py: a beta-era NayaFlow database out to OpenFlow's profile JSON and
back into its own schema, with the beta forms translated each way and nothing lost.

The synthetic database below has the shape of the real one compared on 2026-09-11: MS-n
setting ids, per-direction Track rows, invert=1 on the stock Track axes, no animation column,
97 key colours per layer. No hardware.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))
_ROOT = next(p for p in _BACKEND.parents if (p / "tools" / "nayaflow_db_convert.py").is_file())
_spec = importlib.util.spec_from_file_location("nayaflow_db_convert", _ROOT / "tools" / "nayaflow_db_convert.py")
cv = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cv)

from openflow_backend.db import database as dbm      # noqa: E402
from openflow_backend.db import profiles as prof     # noqa: E402


def _beta_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE profiles (name TEXT, order_id INT, state TEXT, icon_id TEXT, author_name TEXT,
                               description TEXT, id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE layers (name TEXT, order_id INT, icon_id TEXT, profile_id TEXT, author_name TEXT,
                             description TEXT, id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE keys (color_hex TEXT, position_id INT, layer_id TEXT, dynamic_layer_id TEXT,
                           id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE key_bindings (context TEXT, action_code TEXT, action_type TEXT, behavior TEXT,
                                   key_id TEXT, id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_configs (name TEXT, order_id INT, icon_id TEXT, author_name TEXT, description TEXT,
                                     size INT, type TEXT, id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT, behavior TEXT,
                                      invert INT, threshold INT, direction TEXT, mode INT,
                                      module_config_id TEXT, id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT, module_config_id TEXT,
                                             binding_location TEXT, state TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_settings (value TEXT, type TEXT, correlation_id TEXT, module_config_id TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE settings (value TEXT, correlation_id TEXT, type TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE macros (name TEXT, type TEXT, icon_id TEXT, order_id INT, duration INT, size INT,
                             author_name TEXT, description TEXT, id TEXT PRIMARY KEY, updated_at TEXT, created_at TEXT);
        CREATE TABLE goose_db_version (id INTEGER PRIMARY KEY, version_id INT, is_applied INT, tstamp TEXT);
        INSERT INTO goose_db_version VALUES (1, 20250929162102, 1, '');
        INSERT INTO profiles VALUES ('Naya Default Windows', 0, 'ON_BOARD', NULL, NULL, NULL, 'p1', '', '');
        INSERT INTO layers VALUES ('QWERTY', 0, NULL, 'p1', NULL, NULL, 'l0', '', '');
        INSERT INTO layers VALUES ('Keypad', 1, NULL, 'p1', NULL, NULL, 'l1', '', '');
        INSERT INTO module_configs VALUES ('Naya Track', 0, NULL, NULL, NULL, 0, 'TRACK', 'trk', '', '');
        INSERT INTO module_configs VALUES ('Naya Track Niri', 1, NULL, NULL, NULL, 0, 'TRACK', 'niri', '', '');
        INSERT INTO module_configs VALUES ('Naya Touch Windows', 0, NULL, NULL, NULL, 0, 'TOUCH', 'tch', '', '');
        INSERT INTO module_config_bindings VALUES ('p1', 'l0', 'trk', 'track:keyboard_left', NULL, '', '');
        INSERT INTO module_config_bindings VALUES ('p1', 'l0', 'trk', 'track:keyboard_right', NULL, '', '');
        INSERT INTO module_config_bindings VALUES ('p1', 'l1', 'niri', 'track:keyboard_right', NULL, '', '');
        INSERT INTO module_config_bindings VALUES ('p1', 'l0', 'tch', 'touch:keyboard_left', NULL, '', '');
        INSERT INTO module_settings VALUES ('50', 'string', 'MS-2', 'tch', '', '');
        INSERT INTO module_settings VALUES ('3', 'string', 'MS-3', 'tch', '', '');
        INSERT INTO module_settings VALUES ('off', 'string', 'MS-5', 'tch', '', '');
        INSERT INTO module_settings VALUES ('10', 'string', 'MS-8', 'trk', '', '');
        INSERT INTO module_settings VALUES ('7', 'string', 'MS-99', 'trk', '', '');
    """)
    for lid in ("l0", "l1"):
        for pos in range(97):
            conn.execute("INSERT INTO keys VALUES (?,?,?,?,?,?,?)", ("#FFA500", pos, lid, None, f"{lid}-{pos}", "", ""))
    conn.execute("INSERT INTO key_bindings VALUES (?,?,?,?,?,?,?,?)", (None, "A", "key", "press", "l0-0", "b1", "", ""))
    conn.execute("INSERT INTO key_bindings VALUES (?,?,?,?,?,?,?,?)", (None, "BT_OUT", "out", "press", "l1-47", "b2", "", ""))
    mb = [("trk", "vertical:track", "mouse - MOUSE_DOWN - MOUSE_UP", "value", "+", 1),
          ("trk", "horizontal:track", "mouse - MOUSE_LEFT - MOUSE_RIGHT", "value", "+", 1),
          ("trk", "tap:track:button_1", "M4", "mouse", "+", 0),
          ("niri", "track_up:track", "LGUI + UP", "combo", "+", 0),
          ("niri", "track_down:track", "LGUI + DOWN", "combo", "+", 0),
          ("niri", "clockwise_rotate:track", None, None, "+", 0),
          ("niri", "counter_clockwise_rotate:track", None, None, "+", 0),
          ("niri", "tap:track:button_1", "M4", "mouse", "+", 0)]
    for i, (cid, beh, code, atype, d, inv) in enumerate(mb):
        conn.execute("INSERT INTO module_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (None, code, atype, beh, inv, 0, d, 0, cid, f"mb{i}", "", ""))
    conn.commit(); conn.close()
    return path


def test_to_json_translates_the_beta_forms_and_stashes_them(tmp_path):
    db = _beta_db(tmp_path / "beta.db")
    (out,) = cv.to_json(db, tmp_path / "p.json")
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["kind"] == "profile" and d["profile"]["name"] == "Naya Default Windows"
    assert [len(l["keys"]) for l in d["layers"]] == [97, 97]
    cfg = {c["name"]: c for c in d["modules"]["configs"]}
    # MS-n -> named ids, toggles as true/false, unknown ids carried through
    assert {(s["correlation_id"], s["value"]) for s in cfg["Naya Touch Windows"]["settings"]} == \
        {("scroll_speed", "50"), ("pointer_speed", "3"), ("pointer_accel_on", "false")}
    assert {(s["correlation_id"], s["value"]) for s in cfg["Naya Track"]["settings"]} == {("pointer_speed", "10"), ("MS-99", "7")}
    # per-direction rows -> axis row + halves; empty per-direction rows dropped
    niri = {(b["behavior"], b["direction"]): (b["action_type"], b["action_code"]) for b in cfg["Naya Track Niri"]["bindings"]}
    assert niri[("vertical:track", "-")] == ("combo", "LGUI + UP") and niri[("vertical:track", "+")] == ("combo", "LGUI + DOWN")
    assert niri[("vertical:track", "+")] != niri.get(("rotate:track", "+"))
    assert ("vertical:track", "+") in niri and any(b["behavior"] == "vertical:track" and b["action_type"] == "value"
                                                  for b in cfg["Naya Track Niri"]["bindings"])
    assert not any(b["behavior"].startswith(("track_", "clockwise", "counter_clockwise")) for b in cfg["Naya Track Niri"]["bindings"])
    # invert cleared, stashed by config name
    assert all(b["invert"] == 0 for b in cfg["Naya Track"]["bindings"])
    beta = d["nayaflowSource"]["beta"]
    assert sorted(beta["invert"]["Naya Track"]) == ["horizontal:track", "vertical:track"]
    assert beta["settingsIds"]["Naya Touch Windows"]["pointer_speed"] == "MS-3"
    assert beta["synthesizedAxes"]["Naya Track Niri"] == ["vertical:track"]
    assert d["nayaflowSource"]["gooseVersions"] == [20250929162102]


def test_the_json_imports_into_openflow_as_a_new_profile(tmp_path, monkeypatch):
    db = _beta_db(tmp_path / "beta.db")
    (out,) = cv.to_json(db, tmp_path / "p.json")
    live = tmp_path / "openflow.db"
    dbm.init_db(live)
    monkeypatch.setattr(prof, "connect", lambda: cv._row_conn(live))
    r = prof.import_profile(json.loads(out.read_text(encoding="utf-8")))
    assert r["ok"]
    conn = cv._row_conn(live)
    try:
        names = {x["name"] for x in conn.execute("SELECT name FROM profiles")}
        assert "Naya Default Windows" in names
        halves = conn.execute("SELECT direction, action_code FROM module_bindings mb JOIN module_configs mc ON mc.id = mb.module_config_id "
                              "WHERE mc.name='Naya Track Niri' AND mb.behavior='vertical:track' AND mb.action_type='combo'").fetchall()
        assert {(h["direction"], h["action_code"]) for h in halves} == {("-", "LGUI + UP"), ("+", "LGUI + DOWN")}
        setts = {s["correlation_id"]: s["value"] for s in conn.execute(
            "SELECT correlation_id, value FROM module_settings ms JOIN module_configs mc ON mc.id = ms.module_config_id WHERE mc.name='Naya Touch Windows'")}
        assert setts["pointer_speed"] == "3" and setts["pointer_accel_on"] == "false"
    finally:
        conn.close()


def test_to_db_writes_his_schema_and_the_round_trip_is_exact(tmp_path):
    db = _beta_db(tmp_path / "beta.db")
    r = cv.roundtrip(db)
    assert r["identical"], r["differences"]
    (out,) = cv.to_json(db, tmp_path / "p.json")
    back = tmp_path / "back.db"
    cv.to_db(out, db, back)
    conn = sqlite3.connect(back)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(layers)")}
        assert "animation_id" not in cols and "module_led_left" not in cols, "his schema, untouched"
        assert conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0] == 194
        rows = {(r[0], r[1], r[2]) for r in conn.execute(
            "SELECT mb.behavior, mb.action_code, mb.invert FROM module_bindings mb JOIN module_configs mc ON mc.id = mb.module_config_id WHERE mc.name='Naya Track Niri'")}
        assert ("track_up:track", "LGUI + UP", 0) in rows and ("clockwise_rotate:track", None, 0) in rows
        inv = {r[0]: r[1] for r in conn.execute(
            "SELECT mb.behavior, mb.invert FROM module_bindings mb JOIN module_configs mc ON mc.id = mb.module_config_id WHERE mc.name='Naya Track'")}
        assert inv["vertical:track"] == 1 and inv["tap:track:button_1"] == 0
        ms = {r[0]: r[1] for r in conn.execute(
            "SELECT ms.correlation_id, ms.value FROM module_settings ms JOIN module_configs mc ON mc.id = ms.module_config_id WHERE mc.name='Naya Touch Windows'")}
        assert ms == {"MS-2": "50", "MS-3": "3", "MS-5": "off"}
    finally:
        conn.close()


def test_an_edit_in_the_json_lands_in_his_file(tmp_path):
    """The point of the tool: change something in OpenFlow's JSON and hand back a database."""
    db = _beta_db(tmp_path / "beta.db")
    (out,) = cv.to_json(db, tmp_path / "p.json")
    d = json.loads(out.read_text(encoding="utf-8"))
    d["layers"][0]["keys"][0]["bindings"] = [{"behavior": "press", "actionType": "key", "actionCode": "B", "context": None}]
    d["layers"][0]["keys"][5]["colorHex"] = "#00FF00"
    out.write_text(json.dumps(d), encoding="utf-8")
    back = tmp_path / "back.db"
    cv.to_db(out, db, back)
    conn = sqlite3.connect(back)
    try:
        assert conn.execute("SELECT action_code FROM key_bindings b JOIN keys k ON k.id=b.key_id WHERE k.position_id=0").fetchone()[0] == "B"
        assert conn.execute("SELECT color_hex FROM keys WHERE position_id=5 AND layer_id=(SELECT id FROM layers WHERE order_id=0)").fetchone()[0] == "#00FF00"
        assert conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 1
    finally:
        conn.close()
