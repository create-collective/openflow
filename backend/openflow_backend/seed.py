"""Seed the OpenFlow data dir from an existing NayaFlow user-data.db.

Lets us develop and test the binding editor against the real recovered dataset
(the stock "Naya Default Windows" profile) with no device attached — the same way
NayaFlow persisted edits offline.

    python -m openflow_backend.seed <path-to-user-data.db>
    python -m openflow_backend.seed          # uses the NayaOS snapshot if present
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from .config import db_path, seed_db_path

log = logging.getLogger("openflow.seed")


def _default_snapshot() -> Path | None:
    """The snapshot that ships with this repository (or with the frozen bundle), wherever it is:
    config.seed_db_path() knows both layouts."""
    return seed_db_path()


DEFAULT_SNAPSHOT = _default_snapshot()


def ensure_seeded() -> Path | None:
    """First run: put the bundled snapshot in place when there is no database yet.

    Called by the app lifespan BEFORE init_db(), which would otherwise create an empty schema and
    the app would open with nothing in it. No-op when a database exists, when OPENFLOW_NO_SEED is
    set (tests, or someone who wants an empty start), or when no snapshot is bundled. The copy
    lands under a temporary name and is renamed into place, so a crash mid-copy never leaves a
    half file for init_db to "migrate". Returns the database path when it seeded, else None."""
    if os.environ.get("OPENFLOW_NO_SEED"):
        return None
    dest = db_path()
    if dest.exists():
        return None
    source = seed_db_path()
    if source is None or not source.is_file():
        return None
    staging = dest.with_name(dest.name + ".seeding")
    shutil.copyfile(source, staging)
    os.replace(staging, dest)
    log.info("first run: seeded %s from %s", dest, source)
    return dest


def seed(source: Path, force: bool = False) -> Path:
    dest = db_path()
    if dest.exists() and not force:
        raise SystemExit(f"{dest} already exists; pass --force to overwrite")
    if not source.exists():
        raise SystemExit(f"source db not found: {source}")
    shutil.copyfile(source, dest)
    return dest


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    source = Path(args[0]) if args else DEFAULT_SNAPSHOT
    if source is None:
        raise SystemExit("no snapshot found in this checkout; pass a path to a user-data.db")
    dest = seed(source, force=force)
    print(f"Seeded {dest} from {source}")


if __name__ == "__main__":
    main()
