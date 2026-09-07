"""The action catalog's shape, and which tabs each context is allowed to see.

The palette is about to be shared between the keymap editor and module gestures, with three more
tabs coming (Tune, Mouse, Apps) written by whoever needs them. Visibility is therefore an
ALLOWLIST declared on the tab itself rather than a hide-list held by the caller: with a hide-list
every new tab appears in the key editor until somebody remembers to exclude it, and nobody adding
a Tune tab is thinking about the keymap editor.

This file is what makes that hold. A tab that forgets to declare its contexts fails here instead
of shipping into a page it does not belong on.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as ac  # noqa: E402

# Every tab the KEYMAP editor may show. Adding a tab here is a deliberate act; a new tab that
# should not appear on Bindings simply is not listed.
KEY_TABS = {"basic", "extended", "layers", "shortcuts", "apps", "mouse"}


def _visible(context: str) -> set:
    return {t["id"] for t in ac.get_catalog()["tabs"]
            if context in t.get("contexts", ["key", "module"])}


def test_the_keymap_editor_sees_exactly_the_tabs_it_should():
    assert _visible("key") == KEY_TABS, (
        "a tab changed which contexts it declares, or a new tab did not declare any -- "
        "an undeclared tab defaults to both contexts and would appear on Bindings")
    print(f"  key context sees {sorted(KEY_TABS)}")


def test_the_mouse_tab_is_visible_on_keys_because_hardware_says_so():
    """This tab was module-only until 2026-09-07 on the reasoning that a key's category
    namespace differed -- category 3 being BLUETOOTH on a key. That was wrong: bluetooth is a
    different RECORD TYPE (0x00), not a different category space.

    Writing `0f 08 03000000 01000000` to layer 0 position 46 and pressing the key produced a
    real left click; `...02000000` produced a right click. Both measured, not inferred.
    tests/test_mouse_on_key.py pins the encoder side.
    """
    assert "mouse" in _visible("key"), "mouse buttons on a key are confirmed to work on hardware"
    assert "mouse" in _visible("module"), "the module context must not have lost the tab"
    print("  mouse tab is visible in both contexts")


def test_layers_are_a_keymap_concept_only():
    """A module gesture has no layer target to name, and the layers tab is synthesized client
    side from the page's own layer list -- which Modules does not have."""
    assert "layers" not in _visible("module")
    print("  module context does not see the layers tab")


def test_every_tab_declares_its_contexts():
    """The default is permissive so a forgotten tab is visible rather than mysteriously missing.
    This is what stops it staying that way."""
    undeclared = [t["id"] for t in ac.get_catalog()["tabs"] if "contexts" not in t]
    assert not undeclared, f"tabs missing a contexts declaration: {undeclared}"
    print("  all tabs declare contexts")


def test_tab_and_entry_shape_is_what_the_palette_consumes():
    """ActionPalette reads tab.categories[].actions[] and picks {code, actionType}. If any of
    those field names move, the palette renders nothing and says nothing."""
    for t in ac.get_catalog()["tabs"]:
        assert {"id", "label", "title", "categories"} <= set(t), t.get("id")
        for cat in t["categories"]:
            assert {"name", "actions"} <= set(cat), (t["id"], cat.get("name"))
            for a in cat["actions"]:
                assert {"code", "label", "actionType"} <= set(a), (t["id"], a)
    print("  tabs -> categories -> actions shape intact")


def test_the_shortcut_dictionary_still_rides_along():
    """Bindings feeds catalog.shortcuts straight into setShortcutTable, so a keycap can say
    'Cycle windows backwards' instead of the raw chord. Reshaping the catalog must not drop it."""
    sc = ac.get_catalog()["shortcuts"]
    assert sc, "catalog.shortcuts is empty"
    for code, v in list(sc.items())[:20]:
        assert v.get("name") and v.get("chord"), code
    print(f"  {len(sc)} shortcuts carried on the catalog")


def test_the_module_action_list_is_unchanged_by_the_move():
    """MODULE_ACTIONS moved to device/module_actions.py. get_modules() must return the identical
    payload -- AxisControls, the Imported fallback and setShortcutTableFromActions all read it."""
    from openflow_backend.db import userdata as ud
    from openflow_backend.device import module_actions as ma
    assert ud.MODULE_ACTIONS is ma.MODULE_ACTIONS
    assert ud.MODULE_ACTIONS[0] == {"code": "", "label": "None", "actionType": "none", "group": ""}
    assert len(ud.MODULE_ACTIONS) > 90
    print(f"  {len(ud.MODULE_ACTIONS)} module actions, re-exported unchanged")


def test_no_function_references_a_name_the_module_lost():
    """Moving MODULE_ACTIONS out of db/userdata.py took _CURSOR_V and _CURSOR_H with it and left
    _ensure_touch_defaults referencing them -- /api/modules returned 500 while the whole suite
    stayed green, because nothing here calls it.

    So: for every function in the modules involved, check each global name it references actually
    resolves. This catches a dangling reference from ANY future move, not just that one.
    """
    import builtins
    import types

    from openflow_backend.db import userdata as ud
    from openflow_backend.device import actions_catalog as acat
    from openflow_backend.device import module_actions as ma

    dangling = []
    for mod in (ud, acat, ma):
        ns = vars(mod)
        for name, fn in list(ns.items()):
            if not isinstance(fn, types.FunctionType) or fn.__module__ != mod.__name__:
                continue
            # A function-level `from x import Y` binds Y as a LOCAL, so it shows up in
            # co_names but is not a global -- exclude anything the function binds itself.
            local = set(fn.__code__.co_varnames) | set(fn.__code__.co_cellvars)
            for ref in fn.__code__.co_names:
                if ref in ns or ref in local or hasattr(builtins, ref):
                    continue
                # co_names also holds attribute names (conn.execute -> "execute"), which are not
                # globals. Only flag a bare name that looks like a module-level constant.
                if ref.isupper() or (ref.startswith("_") and ref[1:2].isupper()):
                    dangling.append(f"{mod.__name__}.{name} -> {ref}")
    assert not dangling, dangling
    print("  no function references a constant its module does not define")


def test_a_split_axis_still_renders_as_one_gesture_row():
    """Splitting an axis INSERTS a per-half row sharing the parent's behavior. Emitting those as
    gesture rows rendered a duplicate "Vertical", and with two rows for one gesture the wrong one
    took the binding. The halves belong on `axes` as minus/plus, not in the row list."""
    import sqlite3
    from unittest import mock
    from openflow_backend.db import userdata as ud

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (id TEXT, name TEXT, type TEXT, size INT, order_id INT,
                                     icon_id TEXT, variant TEXT, captured_from TEXT,
                                     updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (id TEXT, module_config_id TEXT, behavior TEXT,
                                      action_type TEXT, action_code TEXT, invert INT,
                                      threshold INT, direction TEXT, mode INT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
    """)
    conn.execute("INSERT INTO module_configs (id,name,type,size,order_id) "
                 "VALUES ('c','T','TUNE',0,0)")
    B = "vertical:tune:1_finger"
    rows = [("r1", B, "value", "mouse - SCROLL_UP - SCROLL_DOWN", "+"),   # the combined row
            ("r2", B, "key", "A", "-"),                                   # a split half
            ("r3", B, "key", "B", "+")]                                   # the other half
    for rid, beh, at, code, d in rows:
        conn.execute("INSERT INTO module_bindings (id,module_config_id,behavior,action_type,"
                     "action_code,invert,threshold,direction,mode) VALUES (?,'c',?,?,?,0,0,?,0)",
                     (rid, beh, at, code, d))
    conn.commit()

    class Keep:
        def __init__(self, c): self._c = c
        def __getattr__(self, n): return getattr(self._c, n)
        def close(self): pass

    with mock.patch.object(ud, "connect", lambda: Keep(conn)), \
         mock.patch.object(ud, "_ensure_gesture_slots", lambda c: None), \
         mock.patch.object(ud, "_ensure_touch_defaults", lambda c: None):
        mod = ud.get_modules()["modules"][0]

    shown = [b for b in mod["bindings"] if b["behavior"] == B]
    assert len(shown) == 1, f"expected one gesture row, got {[b['actionCode'] for b in shown]}"
    assert shown[0]["actionCode"] == "mouse - SCROLL_UP - SCROLL_DOWN", "the combined row must win"
    axis = next(a for a in mod["axes"] if a["behavior"] == B)
    assert axis["minus"] == "A" and axis["plus"] == "B", "the halves belong on the axis entry"
    print("  one row for a split axis; halves carried on `axes`")


def test_clearing_a_split_half_cannot_delete_the_gesture():
    """set_axis_split deletes non-compound rows for the behavior+direction it is writing. If the
    axis's last remaining row was a plain one, that deleted the gesture outright and it vanished
    from the UI -- there was nothing left to render. It must fall back to the motion default."""
    import sqlite3
    from unittest import mock
    from openflow_backend.db import userdata as ud
    from openflow_backend.device import module_fields as MF

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (id TEXT, name TEXT, type TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT,
                                      behavior TEXT, invert INT, threshold INT, direction TEXT,
                                      mode INT, module_config_id TEXT, id TEXT,
                                      updated_at TEXT, created_at TEXT);
    """)
    conn.execute("INSERT INTO module_configs VALUES ('c','T','TUNE')")
    B = "vertical:tune:1_finger"
    # The damaging shape: one row, NOT compound, so the delete does not spare it.
    conn.execute("INSERT INTO module_bindings (action_code, action_type, behavior, invert, "
                 "threshold, direction, mode, module_config_id, id, updated_at, created_at) "
                 "VALUES ('','none',?,0,0,'+',0,'c','r1','','')", (B,))
    conn.commit()

    class Keep:
        def __init__(self, c): self._c = c
        def __getattr__(self, n): return getattr(self._c, n)
        def close(self): pass

    with mock.patch.object(ud, "connect", lambda: Keep(conn)):
        ud.set_axis_split("c", B, "+", None)

    left = conn.execute("SELECT action_code FROM module_bindings WHERE behavior=?", (B,)).fetchall()
    assert len(left) == 1, f"the gesture lost its row: {left}"
    assert left[0]["action_code"] == MF.axis_halves("TUNE")[B]["default"]
    print("  clearing a half restores the motion default instead of deleting the gesture")


def test_the_module_tab_is_module_only_and_carries_the_gesture_vocabulary():
    """The 102 module actions were reachable only through the per-gesture dropdown: one flat
    list, no grouping. They now have a palette tab -- and it must NOT appear on Bindings, since
    a keycap has no field for a scroll pair or an LED action."""
    cat = ac.get_catalog()
    tab = next((t for t in cat["tabs"] if t["id"] == "module"), None)
    assert tab is not None, "no module tab in the catalog"
    assert tab["contexts"] == ["module"], "must not leak into the keymap editor"
    assert "module" not in KEY_TABS and _visible("key") == KEY_TABS
    assert "module" in _visible("module")

    from openflow_backend.device.module_actions import MODULE_ACTIONS
    in_tab = {a["code"] for c in tab["categories"] for a in c["actions"]}
    expected = {a["code"] for a in MODULE_ACTIONS if a.get("code")}
    assert in_tab == expected, "every module action with a code should be reachable"
    assert "" not in in_tab, "the None entry is the row's own control, not a palette button"
    print(f"  module tab: {len(tab['categories'])} groups, {len(in_tab)} actions, module-only")


def test_the_module_groups_lead_with_what_a_gesture_is_usually_bound_to():
    """13 groups sorted alphabetically buries Clicks and Scroll under 'App navigation'."""
    tab = next(t for t in ac.get_catalog()["tabs"] if t["id"] == "module")
    names = [c["name"] for c in tab["categories"]]
    assert names[0] == "Clicks", names
    assert names.index("Cursor") < names.index("Caret & selection"), names
    assert len(names) == len(set(names)), "a group must not appear twice"
    print(f"  group order: {', '.join(names[:4])}...")


def test_the_apps_tab_carries_no_categories_and_that_is_deliberate():
    """5,311 chords across 20 applications cannot be a grid of buttons, so the tab has its own
    render branch -- an app selector, a search box and a paged list. It ships with categories
    EMPTY, which the palette has to tolerate the same way it tolerates the layers tab (whose
    categories are synthesized client side)."""
    tab = next((t for t in ac.get_catalog()["tabs"] if t["id"] == "apps"), None)
    assert tab is not None and tab["categories"] == []
    assert set(tab["contexts"]) == {"key", "module"}, "a chord binds on a keycap or a gesture"
    # And the payload stays small: the 1.2 MB of app data must NOT ride along on the catalog.
    assert len(json.dumps(ac.get_catalog())) < 400_000, "catalog got fat -- is app data in it?"
    print("  apps tab present, both contexts, catalog still small")
