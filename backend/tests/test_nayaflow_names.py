"""Every palette entry NayaFlow also offers carries NayaFlow's name and tooltip.

"BT 1" with a tooltip of "BT 1 (BT_DEVICE_1)" told a Naya owner nothing; NayaFlow calls it
"Select BT Device 1" and explains "Select bluetooth device 1." Those strings were scraped from
flow-bg-server.exe on 2026-09-09 (docs/reference/nayaflow-key-palette.json) and are now shipped
inside the backend package (nayaflow_names.json, built by tools/build_nayaflow_names.py). The
palette shows them as each action's name and tooltip; our keycap legend stays; our own
sentence-case name survives as an alias so search still finds it. No hardware.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as AC   # noqa: E402

# The repo root is wherever tools/ lives: two levels up in NayaOS, one in the OpenFlow repo.
ROOT = next(p for p in _BACKEND.parents if (p / "tools" / "build_nayaflow_names.py").is_file())
NAMES = _BACKEND / "openflow_backend" / "device" / "nayaflow_names.json"


def _actions():
    for t in AC.get_catalog()["tabs"]:
        for c in t.get("categories") or []:
            for a in c.get("actions") or []:
                yield t["id"], a


def test_the_shipped_names_file_matches_the_scrape():
    """The package copy must not drift from the reference scrape it was built from."""
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_nayaflow_names.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_names_file_is_substantial():
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    assert len(names) >= 360
    assert sum(1 for v in names.values() if v["tooltip"]) >= 360


def test_the_connection_keys_say_what_they_do():
    by = {a["code"]: a for _t, a in _actions()}
    assert by["BT_OUT"]["label"] == "Wireless", "the keycap legend stays terse"
    assert by["BT_OUT"]["name"] == "Connect via Wireless"
    assert by["BT_OUT"]["tooltip"] == "Output to selected wireless device."
    assert by["USB_DEVICE"]["name"] == "Connect via USB Cable"
    assert by["BT_DEVICE_1"]["name"] == "Select BT Device 1"
    assert by["BT_CLEAR"]["name"] == "Bluetooth Clear and Pair"
    assert "pairing mode" in by["BT_CLEAR"]["tooltip"]


def test_our_own_sentence_case_name_survives_as_an_alias():
    by = {a["code"]: a for _t, a in _actions()}
    a = by["LED_BREATHE"]
    assert a["name"] == "LED Effect Breathe" and a["alias"] == "Lighting: Breathe"
    assert a["label"] == "Breathe"
    assert "breathe" in a["tooltip"].lower()


def test_every_entry_has_a_name_and_nayaflow_entries_have_a_tooltip():
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    # SEMICOLON is the one code NayaFlow ships without a tooltip; only what the scrape has is owed.
    #
    # A chord we renamed is the exception, and deliberately so (SCRUM-83): NayaFlow's tooltip
    # describes NayaFlow's reading of that chord, so under the Windows preset for Ctrl+Up it
    # said "Open Mission Control." beneath "Move to previous paragraph". It moves to
    # `aliasTooltip` with the name it belongs to rather than sitting under a name it contradicts.
    missing_tip = [a["code"] for _t, a in _actions()
                   if names.get(a["code"], {}).get("tooltip")
                   and not a.get("tooltip") and not a.get("aliasTooltip")]
    assert not missing_tip, missing_tip
    no_name = [a["code"] for _t, a in _actions() if not a.get("name")]
    assert not no_name, no_name


def test_the_flat_names_map_covers_every_palette_code():
    cat = AC.get_catalog()
    codes = {a["code"] for _t, a in _actions()}
    assert codes <= set(cat["names"])
    assert cat["names"]["BT_OUT"]["tooltip"].startswith("Output to")


def test_a_missing_names_file_degrades_to_our_own_labels(monkeypatch, tmp_path):
    monkeypatch.setattr(AC, "_NAMES_FILE", tmp_path / "absent.json")
    by = {a["code"]: a for t in AC.get_catalog()["tabs"] for c in t.get("categories") or []
          for a in c.get("actions") or []}
    assert by["BT_OUT"]["name"] == "Wireless" and "tooltip" not in by["BT_OUT"]


# --- tooltips are the vendor's text, whole, and nothing we invented ------------------------- #

def test_no_tooltip_is_marked_truncated_any_more():
    """THE BUG. An ellipsis was appended to any tooltip not ending in `.!?)`, to flag the single
    one the scrape cut short. It fired on 178 of 377, because most tooltips are short labels with
    no terminal punctuation -- users were shown "Escape…", "Shift…", "A…", implying held-back text
    that never existed. Search ranks tooltips last partly because of this, and the palette and the
    bound-key panel both display them."""
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    marked = {c: v["tooltip"] for c, v in names.items() if v["tooltip"].endswith("…")}
    assert not marked, marked


def test_the_one_genuinely_cut_tooltip_carries_its_real_ending():
    """MODULE_FORCE_CHARGING was the reason the rule existed; the scrape stopped at "keyboard to".

    The ending is RECOVERED, not authored: it is taken verbatim from NayaFlow 1.25.1's own string
    table and corroborated against an independent build (1.17.3's app.asar), which carries the
    identical sentence. If this ever has to be re-derived, that is where it comes from."""
    t = json.loads(NAMES.read_text(encoding="utf-8"))["MODULE_FORCE_CHARGING"]["tooltip"]
    assert t.endswith("Restart your keyboard to turn OFF this mode.")
    assert t.startswith("Activate Recovery Mode to recover module from a critically drained")


def test_short_labels_keep_their_own_wording_untouched():
    """The other side of it: no punctuation is added to a label either. A tooltip is the vendor's
    string, byte for byte, or it is the recovered one."""
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    for code, want in [("A", "A"), ("ESC", "Escape"), ("LSHIFT", "Shift")]:
        assert names[code]["tooltip"] == want, (code, names[code]["tooltip"])


def test_nearly_every_tooltip_ends_in_punctuation_or_is_a_short_label():
    """A guard against a future scrape quietly truncating sentences. Anything that reads as prose
    -- more than seven words -- must terminate properly; short labels are exempt because that is
    what they are."""
    bad = [(c, v["tooltip"]) for c, v in json.loads(NAMES.read_text(encoding="utf-8")).items()
           if len(v["tooltip"].split()) > 7 and v["tooltip"][-1:] not in (".", "!", "?", ")", "")]
    assert not bad, bad
