"""NayaFlow user-data.db  <->  OpenFlow profile JSON, without touching anyone's live database.

    python tools/nayaflow_db_convert.py to-json  user-data.db  out.json
    python tools/nayaflow_db_convert.py to-db    in.json --template user-data.db  out.db
    python tools/nayaflow_db_convert.py roundtrip user-data.db          # prove the two cancel

WHY. Another owner's NayaFlow database (a beta-era one, 2026-09-11) needed comparing and editing,
but OpenFlow's "Import backup file" installs a database wholesale, and he has no OpenFlow to
flash from. So: read his file into a THROWAWAY copy, normalise the beta forms there, and export
the app's own profile JSON (`kind: "profile"`, importable with "Import profile" as a NEW profile
beside yours). Then write the edited JSON back into a copy of HIS ORIGINAL FILE, which keeps his
schema byte for byte -- his NayaFlow reads it -- with the beta forms restored.

WHAT THE BETA SCHEMA DOES DIFFERENTLY (all measured on that file):
  * module_settings rows are keyed `MS-n`, not by the field id. The numbering follows the
    settings schema per module type: Touch MS-2..5, Track MS-7..10, Tune MS-11..17, each in the
    order scroll speed, pointer speed, acceleration, acceleration on (+ the Tune's three tick
    fields). Evidence: his Touch has MS-2 50 / MS-3 3 / MS-4 50 / MS-5 off and his "Naya Tune
    Fast" has only MS-12 50 -- a raised pointer speed is what "Fast" means. BEST EVIDENCE, NOT
    A CAPTURE: unmapped ids are carried through untouched under their MS name so nothing is
    lost either way.
  * A split Track axis is stored as separate per-direction rows -- track_up / track_down /
    track_left / track_right / clockwise_rotate / counter_clockwise_rotate -- where OpenFlow
    and NayaFlow 1.25.1 store one axis row plus a per-half row with a direction column.
  * The stock Track axes carry invert=1. OpenFlow implements invert for real (it flips the
    selector signs at flash), so that flag is cleared on the way out and stashed in the JSON,
    and put back on the way in.
  * layers has no animation column and no module colour columns; keys has 97 colours per
    layer. Both survive: the export reads the (added, empty) animation column and the import
    writes back only the columns his schema has.

No device. No write to any path but the one you name.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "openflow" if (ROOT / "openflow" / "backend").is_dir() else ROOT
sys.path.insert(0, str(APP / "backend"))
sys.path.insert(0, str(APP / "backend" / "openflow_backend" / "_vendor"))

from openflow_backend.db.nayaflow_convert import (  # noqa: E402,F401
    BETA_HALVES, BETA_SETTING_IDS, _row_conn, _shape, roundtrip, to_db, to_json, to_json_payloads,
)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("to-json"); a.add_argument("db", type=Path); a.add_argument("out", type=Path)
    b = sub.add_parser("to-db"); b.add_argument("json", type=Path); b.add_argument("--template", type=Path, required=True); b.add_argument("out", type=Path)
    c = sub.add_parser("roundtrip"); c.add_argument("db", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "to-json":
        for p in to_json(args.db, args.out):
            print(f"wrote {p}")
    elif args.cmd == "to-db":
        print(json.dumps(to_db(args.json, args.template, args.out)))
    else:
        r = roundtrip(args.db)
        print("round trip identical" if r["identical"] else f"round trip DIFFERS in {r['differences']}")
        return 0 if r["identical"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
