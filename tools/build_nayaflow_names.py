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
# NayaOS keeps the app under openflow/; the OpenFlow repo has backend/ at the top.
APP = ROOT / "openflow" if (ROOT / "openflow" / "backend").is_dir() else ROOT
OUT = APP / "backend" / "openflow_backend" / "device" / "nayaflow_names.json"


# The scrape cut exactly ONE tooltip short, and this is its real ending.
#
# An ellipsis used to be appended to any tooltip not ending in `.!?)`, to mark that one. The rule
# fired on 178 of 377 entries, because most tooltips are short labels that legitimately carry no
# terminal punctuation -- "Escape" was shown to users as "Escape…", implying text we were hiding
# and had never held. It was our own invention, not the vendor's data.
#
# Which ones were genuinely cut was then settled by measurement rather than by a heuristic: every
# scraped tooltip was searched for in NayaFlow 1.25.1's own string table as a quoted literal.
# 356 of 366 appear complete, terminated by the closing quote. Seven did not match for reasons
# that are not truncation -- BACKSLASH is escaped in the dump, and six carry curly quotes
# (U+2018/201C/201D) -- and all of them already end in punctuation or are single symbols. Exactly
# one was a strict PREFIX of a longer literal:
#
#     MODULE_FORCE_CHARGING   scraped: "... Restart your keyboard to"
#                             actual:  "... Restart your keyboard to turn OFF this mode."
#
# The ending below is taken verbatim from that string table and corroborated against an
# independent build, NayaFlow 1.17.3's app.asar, which carries the identical sentence. It is
# recovered text, not authored text; nothing here is guessed.
RECOVERED = {
    "MODULE_FORCE_CHARGING":
        "Activate Recovery Mode to recover module from a critically drained battery. Your module "
        "will not be functional while in recovery mode. Restart your keyboard to turn OFF this "
        "mode.",
}


def build() -> dict:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    out: dict = {}
    for e in data["key_actions"]:
        code = e["actionCode"]
        if code in out:
            continue                                   # first (US) entry wins
        m = re.search(r"tooltip=([^;]*)", e.get("notes") or "")
        tooltip = (m.group(1).strip() if m else "")
        tooltip = RECOVERED.get(code, tooltip)
        icon = re.search(r"icon=([A-Za-z0-9_]+)", e.get("notes") or "")
        out[code] = {"name": (e.get("label") or "").strip(),
                     "tooltip": tooltip,
                     "category": e.get("category") or "",
                     # The keycap icon NayaFlow draws, by file name under icons/action/.
                     "icon": icon.group(1) if icon else ""}
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
