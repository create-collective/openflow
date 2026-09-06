"""Per-application shortcuts, served on demand.

5,311 chords across 20 applications (ShortcutMapper, MIT -- see
docs/reference/ATTRIBUTION.md). That is 1.2 MB, so unlike the 82-entry shortcut dictionary it
cannot ride along on the action catalog, which every page fetches on load. It is loaded once
into memory here and queried per app.

Every chord in the file was validated through remap.encode_keypress when it was generated, so
what is served is bindable -- entries that could not be expressed as a single chord (two-key
sequences, a held SPACE used as a modifier) were dropped at import rather than shipped broken.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# docs/reference/ lives at the repo root, four levels up from this file.
_FILE = (Path(__file__).resolve().parents[4] / "docs" / "reference" / "app-shortcuts.json")

PLATFORMS = ("windows", "mac")


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8")).get("apps") or {}
    except (OSError, ValueError):
        return {}


def apps() -> list[dict]:
    """The application list for the picker: name and how many chords each has."""
    return [{"name": n, "actions": len(v.get("actions") or {})}
            for n, v in sorted(_data().items())]


def search(app: str, platform: str = "windows", q: str = "",
           limit: int = 200, offset: int = 0) -> dict:
    """Chords for one app, optionally filtered.

    Paged rather than returned whole: Blender alone has 741, and a palette that renders every
    one of them is slower to use than the menu it replaces.
    """
    platform = platform if platform in PLATFORMS else "windows"
    actions = (_data().get(app) or {}).get("actions") or {}
    needle = (q or "").strip().lower()

    rows = []
    for name, a in actions.items():
        entry = a.get(platform)
        if not entry or not entry.get("chord"):
            continue                      # no chord on this platform: nothing to bind
        ctx = a.get("context") or ""
        if needle and needle not in name.lower() and needle not in ctx.lower() \
                and needle not in entry["chord"].lower():
            continue
        rows.append({"name": name, "context": ctx, "chord": entry["chord"]})

    rows.sort(key=lambda r: r["name"].lower())
    return {"app": app, "platform": platform, "total": len(rows),
            "items": rows[offset:offset + max(1, min(limit, 500))]}
