"""Turn NayaFlow's palette scrape into the names + tooltips the OpenFlow palette shows.

    python tools/build_nayaflow_names.py            # rewrites openflow_backend/device/nayaflow_names.json
    python tools/build_nayaflow_names.py --check    # exit 1 if the committed file is stale

Source: docs/reference/nayaflow-key-palette.json (376 entries scraped from flow-bg-server.exe,
2026-09-09). Output: {actionCode: {"name", "tooltip", "category"}} for every unique action code.
The US entry wins when a code appears twice (JIS display-context duplicates carry the same
tooltip). The output lives inside the backend package so a packaged app carries it without the
docs tree; tests/test_nayaflow_names.py fails if it drifts from the scrape.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "reference" / "nayaflow-key-palette.json"
OUT = ROOT / "openflow" / "backend" / "openflow_backend" / "device" / "nayaflow_names.json"


def build() -> dict:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    out: dict = {}
    for e in data["key_actions"]:
        code = e["actionCode"]
        if code in out:
            continue                                   # first (US) entry wins
        m = re.search(r"tooltip=([^;]*)", e.get("notes") or "")
        tooltip = (m.group(1).strip() if m else "")
        # One tooltip (MODULE_FORCE_CHARGING) is cut off inside the binary's string table itself,
        # ending "Restart your keyboard to". Mark that rather than guess how the sentence ended.
        if tooltip and tooltip[-1] not in ".!?)":
            tooltip += "…"
        out[code] = {"name": (e.get("label") or "").strip(),
                     "tooltip": tooltip,
                     "category": e.get("category") or ""}
    return dict(sorted(out.items()))


def main(argv: list[str]) -> int:
    built = build()
    text = json.dumps(built, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT} is stale; run {Path(__file__).name}")
            return 1
        print(f"{OUT.name} matches the scrape ({len(built)} codes)")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(built)} codes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
