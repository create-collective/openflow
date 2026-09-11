"""The "Load profile from file" route takes a NayaFlow database as readily as a JSON export.

A .db (or a NayaFlow backup .zip bundling one) is converted in a throwaway copy and every
profile it holds is imported as a NEW profile beside the user's own; the current database is
never replaced, which is the difference from /rpc/import-backup-file. No hardware.
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))
sys.path.insert(0, str(_BACKEND / "tests"))

from openflow_backend.api import rest                      # noqa: E402
from openflow_backend.db import database as dbm            # noqa: E402
from openflow_backend.db import profiles as prof           # noqa: E402
from test_nayaflow_db_convert import _beta_db              # noqa: E402

app = FastAPI()
app.include_router(rest.router)
client = TestClient(app)


def _live(tmp_path, monkeypatch) -> Path:
    live = tmp_path / "openflow.db"
    dbm.init_db(live)

    def connect():
        c = sqlite3.connect(live); c.row_factory = sqlite3.Row; c.execute("PRAGMA foreign_keys = ON"); return c
    monkeypatch.setattr(prof, "connect", connect)
    return live


def _names(live) -> set:
    c = sqlite3.connect(live)
    try:
        return {r[0] for r in c.execute("SELECT name FROM profiles")}
    finally:
        c.close()


def test_a_nayaflow_database_imports_as_new_profiles(tmp_path, monkeypatch):
    live = _live(tmp_path, monkeypatch)
    before = _names(live)
    raw = _beta_db(tmp_path / "beta.db").read_bytes()
    r = client.post("/rpc/import-profile-file", files={"file": ("user-data-beta.db", raw, "application/octet-stream")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "nayaflow-db" and [x["name"] for x in body["imported"]] == ["Naya Default Windows"]
    assert _names(live) == before | {"Naya Default Windows"}, "added beside, nothing replaced"


def test_a_backup_zip_bundling_the_database_works_too(tmp_path, monkeypatch):
    live = _live(tmp_path, monkeypatch)
    raw = _beta_db(tmp_path / "beta.db").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("backup/user-data.db", raw)
    r = client.post("/rpc/import-profile-file", files={"file": ("nayaflow-backup.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert "Naya Default Windows" in _names(live)


def test_a_json_export_still_goes_the_old_way(tmp_path, monkeypatch):
    live = _live(tmp_path, monkeypatch)
    data = {"version": 1, "kind": "profile", "profile": {"name": "From JSON"}, "layers": [], "macros": [], "modules": {}}
    r = client.post("/rpc/import-profile-file", files={"file": ("x.openflow-profile.json", json.dumps(data).encode(), "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "json" and "From JSON" in _names(live)


def test_junk_is_refused_with_a_reason(tmp_path, monkeypatch):
    _live(tmp_path, monkeypatch)
    r = client.post("/rpc/import-profile-file", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "expected" in r.text
    r = client.post("/rpc/import-profile-file", files={"file": ("bad.db", b"not a database", "application/octet-stream")})
    assert r.status_code == 400


def test_an_imported_track_profile_is_tagged_with_its_side_when_that_is_unambiguous(tmp_path, monkeypatch):
    """The Bindings bay picker offers Track profiles by side tag. An import derives the tag from
    the payload's own bay assignments: one side -> that side; both sides or none -> untagged,
    which the picker now offers in either bay."""
    live = _live(tmp_path, monkeypatch)
    data = {"version": 1, "kind": "profile", "profile": {"name": "Sides"}, "macros": [],
            "layers": [{"srcId": "L0", "name": "Base", "orderId": 0, "keys": []},
                       {"srcId": "L1", "name": "Alt", "orderId": 1, "keys": []}],
            "modules": {"configs": [
                {"srcId": "left-only", "name": "Left only", "type": "TRACK", "bindings": [], "settings": []},
                {"srcId": "both", "name": "Both docks", "type": "TRACK", "bindings": [], "settings": []},
                {"srcId": "tune", "name": "A Tune", "type": "TUNE", "bindings": [], "settings": []},
            ], "configBindings": [
                {"srcLayerId": "L1", "srcConfigId": "left-only", "bindingLocation": "track:keyboard_left", "state": None},
                {"srcLayerId": "L0", "srcConfigId": "both", "bindingLocation": "track:keyboard_left", "state": None},
                {"srcLayerId": "L0", "srcConfigId": "both", "bindingLocation": "track:keyboard_right", "state": None},
                {"srcLayerId": "L0", "srcConfigId": "tune", "bindingLocation": "tune:keyboard_left", "state": None},
            ]}}
    r = client.post("/rpc/import-profile-file", files={"file": ("sides.json", json.dumps(data).encode(), "application/json")})
    assert r.status_code == 200, r.text
    c = sqlite3.connect(live)
    try:
        tags = {name: v for name, v in c.execute("SELECT name, variant FROM module_configs WHERE name IN ('Left only','Both docks','A Tune')")}
    finally:
        c.close()
    assert tags == {"Left only": "TRACK_LEFT", "Both docks": None, "A Tune": "TUNE"}
