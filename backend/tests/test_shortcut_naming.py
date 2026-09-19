"""What a chord is CALLED, per category (SCRUM-83).

NayaFlow carries one global name per chord and it is macOS- and editor-flavoured. Letting it win
meant Ctrl+Up was presented as "Mission Control" under every category at once -- including the
Windows one -- so a tester searched for a macOS action, bound a Windows chord that scrolls a
line, and reported it. The palette search ranks and displays that name, which is the surface
the report came through.

The rule now: a chord is named by the most specific source that knows about it, and the name it
displaces is kept as an alias so search still finds it. Device vocabulary (LED effects, the
Bluetooth keys) is untouched -- NayaFlow's names there are the better ones.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as AC  # noqa: E402
from openflow_backend.device import shortcuts as SC  # noqa: E402


def _entries(code):
    """Every place a code appears: (tab id, category, the described action)."""
    cat = AC.get_catalog()
    return [(t["id"], c["name"], a)
            for t in cat["tabs"] for c in (t.get("categories") or [])
            for a in (c.get("actions") or []) if a["code"] == code]


def _one(code, tab, category):
    got = [a for t, c, a in _entries(code) if t == tab and c == category]
    assert got, f"{code} is not in {tab}/{category}"
    return got[0]


def test_a_chord_is_named_for_the_category_it_is_listed_under():
    """The report itself: one chord, three preset categories, one macOS name on all of them."""
    mac = _one("LCTRL + UP", "shortcuts", "MacOS")
    win = _one("LCTRL + UP", "shortcuts", "Windows")
    code = _one("LCTRL + UP", "shortcuts", "VS Code Presets")
    assert mac["name"] == "Mission Control", "under MacOS that name is correct and stays"
    assert win["name"] != "Mission Control", "the Windows preset must not be named for macOS"
    assert code["name"] != "Mission Control", "nor the VS Code one"
    assert win["name"] == "Move to previous paragraph"
    assert code["name"] == "Scroll Line Up"
    print("  one chord, three categories, three truthful names")


def test_our_dictionary_name_wins_where_we_have_one():
    a = _one("LCTRL + UP", "module", "Caret & selection")
    assert a["name"] == "Scroll up one line", "our platform-tagged name leads"
    assert a["alias"] == "Mission Control", "what it displaced stays searchable"
    print("  our dictionary leads and keeps the displaced name as an alias")


def test_the_displaced_name_is_still_findable():
    """Someone who knows the macOS name must still be able to search for it."""
    for _t, _c, a in _entries("LCTRL + UP"):
        assert a["name"] == "Mission Control" or a.get("alias") == "Mission Control", \
            f"{a['name']} neither is nor carries the displaced name"
    print("  every listing of the chord is reachable by the old name")


def test_a_displaced_tooltip_travels_with_its_own_name():
    """"Open Mission Control." must not sit under "Move to previous paragraph"."""
    win = _one("LCTRL + UP", "shortcuts", "Windows")
    assert "mission control" not in (win.get("tooltip") or "").lower()
    assert "Mission Control" in (win.get("aliasTooltip") or ""), \
        "the tooltip should follow the alias, not be thrown away"
    print("  the tooltip follows the name it describes")


def test_task_view_is_not_called_switch_to_previous_app():
    a = _one("LGUI + TAB", "module", "Windows & desktops")
    assert a["name"] == "Task view" and a["alias"] == "Switch to Previous App"
    print("  Win+Tab reads as Task view")


def test_a_function_key_keeps_its_meaning():
    """NayaFlow names F11 "F11", which tells you nothing you cannot see on the key."""
    a = _one("F11", "module", "Tabs & browser")
    assert a["name"] == "Full screen"
    print("  F11 means Full screen, not F11")


def test_device_vocabulary_is_left_alone():
    """The flip is scoped to chords. For LED and Bluetooth keys NayaFlow's names are better."""
    by = {a["code"]: a for _t, _c, a in
          [(t["id"], c["name"], a) for t in AC.get_catalog()["tabs"]
           for c in (t.get("categories") or []) for a in (c.get("actions") or [])]}
    led = by["LED_BREATHE"]
    assert led["name"] == "LED Effect Breathe" and led["alias"] == "Lighting: Breathe"
    assert "breathe" in led["tooltip"].lower(), "and it keeps its tooltip"
    print("  LED and Bluetooth vocabulary is unchanged")


# --- the dictionary itself ---------------------------------------------------------------------

def test_the_names_the_semantic_pass_corrected():
    """Four chords where OUR name described a different action than the chord performs."""
    by = {s["code"]: s for s in SC.all_shortcuts()}
    assert by["LSHIFT + F5"]["name"] == "Stop debugging"        # not "Hard refresh"
    assert by["LSHIFT + F8"]["name"] == "Previous problem"      # not "Step back (debugger)"
    assert by["LSHIFT + LALT + I"]["name"] == "Add cursor to line ends"  # not "Toggle inspector"
    assert by["LCTRL + F4"]["name"] == "Close document"         # not "Close tab"
    assert by["LSHIFT + F11"]["group"] == "Function keys"       # was filed under Tabs & browser
    print("  the four corrected names, and the regrouped one")


def test_the_everyday_chords_that_were_missing():
    by = {s["code"]: s for s in SC.all_shortcuts()}
    for code, name in [("LCTRL + W", "Close tab"), ("LCTRL + S", "Save"),
                       ("LCTRL + LSHIFT + R", "Hard refresh"), ("LGUI + L", "Lock the computer"),
                       ("LCTRL + LSHIFT + I", "Developer tools")]:
        assert code in by, f"{code} is still missing"
        assert by[code]["name"] == name
    print("  the gaps the pass found are filled")


def test_every_chord_still_encodes_to_the_bytes_it_claims():
    """Including the ones added by hand: what is displayed must be what would be flashed."""
    from openflow_backend.device import remap as R
    bad = []
    for s in SC.all_shortcuts():
        got = R.encode_keypress("shortcut_alias", s["code"]).hex()
        if got != (s.get("bytes") or "").lower():
            bad.append((s["chord"], s.get("bytes"), got))
    assert not bad, bad
    print(f"  all {len(SC.all_shortcuts())} chords encode to the bytes they carry")
