"""Bundled resources are found from one place, and a first run starts from the snapshot.

config.reference_dir(), renderer_dir() and seed_db_path() replaced three copies of a
parent-directory walk (device/app_shortcuts.py, device/shortcuts.py, api/rest.py) and the seed
CLI's own; in a source checkout they walk up from the package, in the frozen sidecar they read
<_MEIPASS>/resources, and OPENFLOW_RESOURCES_DIR overrides both. seed.ensure_seeded() runs in
the lifespan before init_db(): without it the desktop app opened empty (seed.py was a manual
CLI nothing invoked). No hardware, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend import config, seed as seed_mod             # noqa: E402
from openflow_backend.db import database as dbm                   # noqa: E402

REFERENCE_FILES = ("app-shortcuts.json", "shortcut-dictionary.json", "firmware-catalog.json", "ATTRIBUTION.md")


def test_a_source_checkout_resolves_every_bundled_file():
    assert not config.is_frozen() and config.resources_dir() is None
    ref = config.reference_dir()
    assert ref is not None and ref.is_dir(), "docs/reference not found above the package"
    for name in REFERENCE_FILES:
        assert (ref / name).is_file(), f"{name} missing from {ref}"
    seed = config.seed_db_path()
    assert seed is not None and seed.is_file(), "the first-run snapshot is missing"
    print(f"  reference={ref}  seed={seed.name}  renderer={config.renderer_dir()}")


def test_an_explicit_resources_dir_wins(tmp_path, monkeypatch):
    (tmp_path / "reference").mkdir()
    (tmp_path / "renderer").mkdir()
    (tmp_path / "seed").mkdir()
    (tmp_path / "seed" / "user-data-x.db").write_bytes(b"")
    monkeypatch.setenv("OPENFLOW_RESOURCES_DIR", str(tmp_path))
    assert config.reference_dir() == tmp_path / "reference"
    assert config.renderer_dir() == tmp_path / "renderer"
    assert config.seed_db_path() == tmp_path / "seed" / "user-data-x.db"
    (tmp_path / "seed" / "user-data-x.db").unlink()
    assert config.seed_db_path() is None, "no *.db in the bundle means no seed, not a crash"
    print("  OPENFLOW_RESOURCES_DIR overrides the checkout walk")


def test_first_run_seeds_then_init_db_migrates_and_the_second_run_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("OPENFLOW_NO_SEED", raising=False)
    dest = seed_mod.ensure_seeded()
    assert dest == config.db_path() and dest.is_file()
    assert not list((tmp_path / "data").glob("*.seeding")), "the staging copy is renamed away"
    dbm.init_db()                                     # the NayaFlow-era snapshot migrates in place
    conn = dbm.connect()
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    profiles = next(t for t in ("profiles", "profile") if t in tables)
    n = conn.execute(f"select count(*) from {profiles}").fetchone()[0]
    conn.close()
    assert n >= 1, "the seeded database carries at least the stock profile"
    assert seed_mod.ensure_seeded() is None, "a database exists: nothing to do"
    print(f"  seeded {dest.name}, {n} profile(s) after init_db, second run is a no-op")


def test_seeding_is_skipped_for_an_existing_database_and_when_opted_out(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFLOW_DATA_DIR", str(tmp_path / "d1"))
    monkeypatch.delenv("OPENFLOW_NO_SEED", raising=False)
    dbm.init_db()                                     # an empty database, as the tests make them
    size = config.db_path().stat().st_size
    assert seed_mod.ensure_seeded() is None and config.db_path().stat().st_size == size
    monkeypatch.setenv("OPENFLOW_DATA_DIR", str(tmp_path / "d2"))
    monkeypatch.setenv("OPENFLOW_NO_SEED", "1")
    assert seed_mod.ensure_seeded() is None and not config.db_path().exists()
    print("  an existing database is left alone; OPENFLOW_NO_SEED starts empty")
