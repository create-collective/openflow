"""Every action that NayaFlow draws an icon for has that icon shipped in the OpenFlow frontend.

The names come from the palette scrape (`icon=` per action, via nayaflow_names.json); the files
are NayaFlow's own SVGs copied by tools/import_nayaflow_icons.py into
openflow/frontend/public/icons/action/, with iconNames.json listing what exists. If a name in
the catalog has no file, the keycap would silently show nothing. No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as AC   # noqa: E402

ROOT = _BACKEND.parents[1]
ICON_DIR = ROOT / "openflow" / "frontend" / "public" / "icons" / "action"
ICON_NAMES = ROOT / "openflow" / "frontend" / "src" / "lib" / "iconNames.json"


def _actions():
    for t in AC.get_catalog()["tabs"]:
        for c in t.get("categories") or []:
            yield from (c.get("actions") or [])


def test_the_icon_set_is_shipped_with_its_provenance():
    assert ICON_DIR.is_dir() and (ICON_DIR / "PROVENANCE.md").exists()
    assert len(list(ICON_DIR.glob("*.svg"))) >= 800


def test_the_name_list_matches_the_files():
    names = json.loads(ICON_NAMES.read_text(encoding="utf-8"))
    files = sorted(p.stem for p in ICON_DIR.glob("*.svg"))
    assert names == files


def test_every_catalog_icon_has_a_file():
    missing = sorted({a["icon"] for a in _actions() if a.get("icon")
                      and not (ICON_DIR / f"{a['icon']}.svg").exists()})
    assert not missing, missing


def test_the_actions_people_notice_carry_an_icon():
    by = {a["code"]: a for a in _actions()}
    assert by["BT_OUT"]["icon"] == "RF_DEVICE"
    assert by["USB_DEVICE"]["icon"] == "USB_DEVICE"
    assert by["LED_BREATHE"]["icon"]
    assert by["MODULE_FORCE_CHARGING"]["icon"] == "MODULE_FORCE_CHARGE"
    assert AC.get_catalog()["names"]["BT_OUT"]["icon"] == "RF_DEVICE"


def test_most_of_the_palette_has_an_icon():
    acts = list(_actions())
    with_icon = sum(1 for a in acts if a.get("icon"))
    assert with_icon >= 360, with_icon


def test_the_shortcuts_tab_is_iconed_including_our_own_alt_tab_pair():
    """190 of the 192 shortcut chords match NayaFlow's exactly and carry its icon; the Windows
    Alt+Tab pair is ours and borrows the Cmd+Tab pair's icons."""
    tab = next(t for t in AC.get_catalog()["tabs"] if t["id"] == "shortcuts")
    acts = [a for c in tab["categories"] for a in c["actions"]]
    assert sum(1 for a in acts if a.get("icon")) == len(acts),         [a["code"] for a in acts if not a.get("icon")]
    by = {a["code"]: a for a in acts}
    assert by["LALT + TAB"]["icon"] == "PREV_APP" and by["LALT + LSHIFT + TAB"]["icon"] == "NEXT_APP"
    for a in acts:
        assert (ICON_DIR / f"{a['icon']}.svg").exists(), a["icon"]
