"""Our shortcut encoder against 80 shortcuts captured from a real NayaFlow flash.

`device/out/flash2-shortcut-dictionary.json` holds the action codes NayaFlow sent AND the exact
param bytes it sent for each. That makes it the strongest offline check we have on
`encode_keypress`: not "does it produce something plausible" but "does it produce the bytes the
vendor's own flash put on the wire".

It is also where the bracketed-modifier rule came from -- see below.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import remap as R  # noqa: E402

DICT = _ROOT / "device" / "out" / "flash2-shortcut-dictionary.json"

# NayaFlow stored "LALT + ENTER" as 00000004 -- modifier only, no usage -- which is the same
# record it writes for "LALT + CLICK". Taken literally that means its Alt+Enter never sends
# Enter. We deliberately do NOT reproduce it: copying a vendor bug into our encoder would break
# a binding that users expect to work.
KNOWN_VENDOR_ANOMALY = {"LALT + ENTER"}


def _captured():
    if not DICT.exists():
        pytest.skip(f"{DICT} not present")
    out = {}
    for p in json.loads(DICT.read_text())["pairs"]:
        out.setdefault(p["action_code"], p["params_hex"])
    return out


def test_the_encoder_reproduces_every_captured_shortcut():
    captured = _captured()
    mismatched = []
    for code, want in captured.items():
        if code in KNOWN_VENDOR_ANOMALY:
            continue
        got = R.encode_keypress("shortcut_alias", code).hex()
        if got != want:
            mismatched.append(f"{code}: want {want}, got {got}")
    assert not mismatched, "\n".join(mismatched)
    print(f"  {len(captured) - len(KNOWN_VENDOR_ANOMALY)} captured shortcuts encode byte-for-byte")


def test_a_bracketed_modifier_does_not_set_its_bit():
    """The rule this file caught. A bracketed modifier marks one the CONTEXT already holds -- an
    app switcher keeping Alt down -- so the record carries only the rest. The code previously
    stripped the brackets and set the bit anyway, which the capture disproves twice."""
    assert R.encode_keypress("shortcut_alias", "[LALT] + TAB").hex() == "2b000700"
    assert R.encode_keypress("shortcut_alias", "[LALT] + LSHIFT + TAB").hex() == "2b000702"
    # ... while an unbracketed one still does.
    assert R.encode_keypress("shortcut_alias", "LALT + TAB").hex() == "2b000704"
    print("  bracketed modifiers excluded, unbracketed included")


def test_a_non_keyboard_base_encodes_as_the_modifier_alone():
    """"LALT + CLICK" is "hold Alt, then click": there is no keyboard usage to send, and the
    device stores the modifier with usage and page both zero."""
    assert R.encode_keypress("shortcut_alias", "LALT + CLICK").hex() == "00000004"
    print("  modifier-only record, page 0")


def test_an_unknown_base_is_still_refused():
    """The modifier-only path must not become a silent catch-all for typos."""
    with pytest.raises(R.RemapEncodeError):
        R.encode_keypress("shortcut_alias", "LCTRL + NOT_A_KEY")
    print("  an unknown base still raises")


# --- the dictionary as a product surface ------------------------------------ #

from openflow_backend.device import shortcuts as SC  # noqa: E402


def test_every_shortcut_has_a_name_a_chord_and_bytes():
    """The whole point is that a row can say what a binding DOES. A missing name silently
    degrades to the raw code, which is what this replaced."""
    missing = [s["code"] for s in SC.all_shortcuts()
               if not s.get("name") or not s.get("chord") or not s.get("bytes")]
    assert not missing, missing
    print(f"  {len(SC.all_shortcuts())} entries, all named")


def test_names_are_plain_english_not_the_chord_again():
    """"Ctrl + Tab" as a NAME teaches the user nothing they could not already read."""
    lazy = [s["code"] for s in SC.all_shortcuts()
            if s["name"].replace(" ", "").lower() == s["chord"].replace(" ", "").lower()]
    assert not lazy, lazy
    assert SC.describe("LALT + LSHIFT + ESC") == "Cycle windows backwards"
    assert SC.describe("LCTRL + LSHIFT + V") == "Paste without formatting"
    print("  names describe the effect, not the keystroke")


def test_an_unknown_code_falls_back_to_itself():
    """Never invent a name. A code we cannot name stays greppable against the device."""
    assert SC.describe("LCTRL + SOMETHING_ODD") == "LCTRL + SOMETHING_ODD"
    assert SC.lookup("LCTRL + SOMETHING_ODD") is None
    print("  unknown codes pass through unchanged")


def test_the_dictionary_bytes_agree_with_the_encoder():
    """The dictionary is a display layer, so it must not drift from what is actually written."""
    from openflow_backend.device import remap as R
    wrong = []
    for s in SC.all_shortcuts():
        try:
            got = R.encode_keypress("shortcut_alias", s["code"]).hex()
        except Exception as e:
            wrong.append(f"{s['code']}: {type(e).__name__}")
            continue
        if got != s["bytes"]:
            wrong.append(f"{s['code']}: dict {s['bytes']} vs encoder {got}")
    assert not wrong, wrong
    print("  every dictionary entry encodes to the bytes it advertises")


def test_the_module_dropdown_shape_keeps_the_keys_visible():
    """A dropdown that says only "Next tab" hides which keys are sent -- on a keyboard
    configurator that is the one thing being chosen."""
    entries = SC.as_module_actions()
    assert entries and all(e["actionType"] == "shortcut_alias" for e in entries)
    tab = next(e for e in entries if e["code"] == "LCTRL + TAB")
    assert tab["label"] == "Next tab  (Ctrl + Tab)", tab["label"]
    assert len({e["group"] for e in entries}) > 1, "should be grouped by purpose, not one bucket"
    print(f"  {len(entries)} dropdown entries across {len(SC.groups())} groups")


# --- the per-platform action chord table ------------------------------------ #

def _chords():
    p = _ROOT / "docs" / "reference" / "action-chords.json"
    if not p.exists():
        pytest.skip("action-chords.json not generated")
    return json.loads(p.read_text(encoding="utf-8"))["actions"]


def test_every_chord_in_the_action_table_actually_encodes():
    """The table exists to be flashed. A chord that will not encode would sit in a dropdown,
    get written, and silently do nothing -- the exact failure we refused to copy from NayaFlow."""
    bad = []
    rows = _chords()
    for a in rows:
        for plat in ("win", "mac", "linux"):
            got = a.get(plat)
            if not got:
                continue
            try:
                if R.encode_keypress("shortcut_alias", got["chord"]).hex() != got["bytes"]:
                    bad.append(f"{a['action']}/{plat}: bytes disagree")
            except Exception as e:
                bad.append(f"{a['action']}/{plat}: {got['chord']} -> {type(e).__name__}")
    assert not bad, bad[:15]
    print(f"  every chord across {len(rows)} actions encodes to the bytes it advertises")


def test_app_specific_actions_are_labelled():
    """An editor binding presented as universal is a lie the user only finds out by flashing."""
    rows = _chords()
    vscode = [a for a in rows if a.get("context") == "vscode"]
    assert vscode, "expected VS Code actions in the table"
    assert all(a["appSpecific"] and a["app"] == "VS Code" for a in vscode)
    os_rows = [a for a in rows if a.get("context") == "os"]
    assert all(not a["appSpecific"] for a in os_rows), "OS bindings must not be app-labelled"
    print(f"  {len(vscode)} VS Code actions labelled, {len(os_rows)} OS actions not")


def test_hardware_actions_claim_no_chord():
    """LED effects and Bluetooth are keyboard functions. Giving them a host chord would be
    inventing one."""
    bad = [a["action"] for a in _chords() if a.get("context") == "keyboard-hardware"
           and any(a.get(p) for p in ("win", "mac", "linux"))]
    assert not bad, bad[:10]
    print("  keyboard-hardware actions carry no chord")


# --- the imported app shortcut dataset -------------------------------------- #

def _apps():
    p = _ROOT / "docs" / "reference" / "app-shortcuts.json"
    if not p.exists():
        pytest.skip("app-shortcuts.json not generated")
    return json.loads(p.read_text(encoding="utf-8"))


def test_every_imported_app_chord_encodes_to_its_stated_bytes():
    """5,000+ chords from an external dataset, all of which we claim can be flashed. If the key
    vocabulary drifts, this is what catches it."""
    d = _apps()
    bad, checked = [], 0
    for app, v in d["apps"].items():
        for action, rec in v["actions"].items():
            for plat in ("windows", "mac", "linux"):
                got = rec.get(plat)
                if not got:
                    continue
                checked += 1
                try:
                    if R.encode_keypress("shortcut_alias", got["chord"]).hex() != got["bytes"]:
                        bad.append(f"{app}/{action}/{plat}")
                except Exception as e:
                    bad.append(f"{app}/{action}/{plat}: {type(e).__name__}")
    assert not bad, bad[:10]
    print(f"  {checked} chords across {len(d['apps'])} apps all encode correctly")


def test_the_import_records_its_source_and_licence():
    """It is someone else's data under MIT. Shipping it without saying so is not acceptable."""
    meta = _apps()["_meta"]
    assert "ShortcutMapper" in meta["source"]
    assert "MIT" in meta["license"]
    print("  source and licence recorded")
