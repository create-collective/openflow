"""Seed the OpenFlow data dir from an existing NayaFlow user-data.db.

Lets us develop and test the binding editor against the real recovered dataset
(the stock "Naya Default Windows" profile) with no device attached — the same way
NayaFlow persisted edits offline.

    python -m openflow_backend.seed <path-to-user-data.db>
    python -m openflow_backend.seed          # uses the NayaOS snapshot if present
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .config import db_path

def _default_snapshot() -> Path | None:
    """The captured snapshot that ships with this repository, wherever it is checked out.

    This was an absolute path into one developer's machine, so the script only ever worked
    there. Walked for instead, so a fresh clone finds its own copy."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "device" / "userdata-snapshot" / "user-data-2026-08-28.db"
        if candidate.is_file():
            return candidate
    return None


DEFAULT_SNAPSHOT = _default_snapshot()


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
