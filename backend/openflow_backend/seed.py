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

# Default: the recovered snapshot in the NayaOS repo (dev convenience only).
DEFAULT_SNAPSHOT = Path(
    r"D:\NayaOS\device\userdata-snapshot\user-data-2026-08-28.db"
)


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
    dest = seed(source, force=force)
    print(f"Seeded {dest} from {source}")


if __name__ == "__main__":
    main()
