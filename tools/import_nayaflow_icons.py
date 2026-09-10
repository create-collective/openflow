"""Bring NayaFlow's action icons into the OpenFlow frontend.

    python tools/import_nayaflow_icons.py            # copy the SVGs + write the name list
    python tools/import_nayaflow_icons.py --check    # exit 1 if the copy is stale

Source: extracted/NayaFlow-1.25.1/asar/dist/renderer/assets/icons/action/*.svg -- the icon set
NayaFlow draws on its keycaps, one file per icon name (the names the palette scrape carries as
`icon=`). Destination: openflow/frontend/public/icons/action/ (served as /icons/action/NAME.svg)
plus openflow/frontend/src/lib/iconNames.json, the sorted list of names that exist, so the UI
never asks for a file that is not there.

PROVENANCE. These are Naya's assets, copied unchanged. The project owner decided on 2026-09-10
to ship them: Naya is defunct and the community it left behind is who this serves. That
decision and the source are recorded in public/icons/action/PROVENANCE.md, written by this
tool; nothing here claims a licence that was not granted.
"""
from __future__ import annotations

import filecmp
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extracted" / "NayaFlow-1.25.1" / "asar" / "dist" / "renderer" / "assets" / "icons" / "action"
DST = ROOT / "openflow" / "frontend" / "public" / "icons" / "action"
NAMES = ROOT / "openflow" / "frontend" / "src" / "lib" / "iconNames.json"

PROVENANCE = """# NayaFlow action icons

Every `.svg` in this directory is copied unchanged from NayaFlow 1.25.1
(`asar/dist/renderer/assets/icons/action/`), the icon set the vendor's app draws on its keycaps.
They are Naya's artwork. The project owner chose on 2026-09-10 to ship them in OpenFlow, on the
grounds that Naya is defunct and these serve the community it left behind. No licence for them
was granted to this project, and none is claimed here.

Regenerate with `python tools/import_nayaflow_icons.py`; `--check` reports drift.
The UI paints them through a CSS mask (`.naya-icon`), so the white fills take the theme's text
colour and the files themselves stay untouched.
"""


def main(argv: list[str]) -> int:
    check = "--check" in argv
    if not SRC.is_dir():
        print(f"source not found: {SRC}")
        return 2
    files = sorted(SRC.glob("*.svg"), key=lambda p: p.name)   # by name: WindowsPath sorts case-insensitively
    names = [p.stem for p in files]
    stale = []
    if check:
        for p in files:
            q = DST / p.name
            if not q.exists() or not filecmp.cmp(p, q, shallow=False):
                stale.append(p.name)
        have = json.loads(NAMES.read_text(encoding="utf-8")) if NAMES.exists() else []
        if have != names:
            stale.append(NAMES.name)
        if not (DST / "PROVENANCE.md").exists():
            stale.append("PROVENANCE.md")
        if stale:
            print(f"{len(stale)} stale: {stale[:8]}{'...' if len(stale) > 8 else ''}")
            return 1
        print(f"{len(names)} icons in sync")
        return 0
    DST.mkdir(parents=True, exist_ok=True)
    for p in files:
        shutil.copyfile(p, DST / p.name)
    (DST / "PROVENANCE.md").write_text(PROVENANCE, encoding="utf-8")
    NAMES.write_text(json.dumps(names, indent=0) + "\n", encoding="utf-8")
    print(f"copied {len(files)} icons -> {DST}; wrote {NAMES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
