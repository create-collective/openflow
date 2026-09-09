"""The shortcut dictionary: plain English, the chord, a glyph, and the device bytes.

The app stored and displayed raw action codes -- a Touch gesture read "LALT + LSHIFT + ESC",
which says what to press and nothing about what it does. This maps each code to a name a person
can read, the chord as it is normally written, a glyph for a tooltip, and the 4-byte KEY_PRESS
param the device actually stores.

Bytes are not invented: 79 of the 80 shortcuts in `device/out/flash2-shortcut-dictionary.json`
were sent by a real NayaFlow flash and our encoder reproduces them exactly (see
tests/test_shortcut_dictionary.py). The one disagreement is recorded per row rather than papered
over -- NayaFlow stored "LALT + ENTER" as a modifier-only record, so its Alt+Enter sends no
Enter, and we deliberately encode the correct bytes instead.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

def _reference_dir() -> Path:
    """Where docs/reference lives.

    Walked for rather than reached by a fixed parent index: NayaOS nests this tree under
    openflow/ while the standalone repository has it at the root, so `parents[4]` is right in one
    layout and points above the drive root in the other."""
    for p in Path(__file__).resolve().parents:
        cand = p / "docs" / "reference"
        if cand.is_dir():
            return cand
    return Path(__file__).resolve().parents[4] / "docs" / "reference"


_DICT = _reference_dir() / "shortcut-dictionary.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    if not _DICT.exists():
        return {"_meta": {}, "shortcuts": []}
    return json.loads(_DICT.read_text(encoding="utf-8"))


def all_shortcuts() -> list[dict]:
    """Every entry, in dictionary order."""
    return list(_load().get("shortcuts", []))


@lru_cache(maxsize=1)
def _by_code() -> dict:
    return {s["code"]: s for s in all_shortcuts()}


def lookup(action_code: str) -> dict | None:
    """The dictionary entry for an action code, or None if we have no name for it."""
    return _by_code().get((action_code or "").strip())


def describe(action_code: str) -> str:
    """Plain English if we know it, otherwise the code unchanged.

    Deliberately falls back to the raw code rather than to a prettified chord: a chord we cannot
    name is better shown exactly as stored, so it stays greppable against the device.
    """
    entry = lookup(action_code)
    return entry["name"] if entry else (action_code or "")


def as_module_actions(group: str | None = None) -> list[dict]:
    """The dictionary in the shape the module/keymap dropdowns consume.

    `label` is the plain-English name with the chord after it, because a dropdown that says only
    "Next tab" hides which keys are being sent -- and on a keyboard configurator that is the one
    thing the user is choosing.
    """
    out = []
    for s in all_shortcuts():
        if group and s.get("group") != group:
            continue
        out.append({
            "code": s["code"],
            "label": f"{s['name']}  ({s['chord']})",
            "name": s["name"],
            "chord": s["chord"],
            "icon": s.get("icon"),
            "platform": s.get("platform", "any"),
            "actionType": "shortcut_alias",
            "group": s.get("group", "Shortcuts"),
        })
    return out


def groups() -> list[str]:
    """Group names in dictionary order, de-duplicated."""
    seen, out = set(), []
    for s in all_shortcuts():
        g = s.get("group", "Shortcuts")
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out
