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

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as ac  # noqa: E402

# Every tab the KEYMAP editor may show. Adding a tab here is a deliberate act; a new tab that
# should not appear on Bindings simply is not listed.
KEY_TABS = {"basic", "extended", "layers", "shortcuts"}


def _visible(context: str) -> set:
    return {t["id"] for t in ac.get_catalog()["tabs"]
            if context in t.get("contexts", ["key", "module"])}


def test_the_keymap_editor_sees_exactly_the_tabs_it_should():
    assert _visible("key") == KEY_TABS, (
        "a tab changed which contexts it declares, or a new tab did not declare any -- "
        "an undeclared tab defaults to both contexts and would appear on Bindings")
    print(f"  key context sees {sorted(KEY_TABS)}")


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
