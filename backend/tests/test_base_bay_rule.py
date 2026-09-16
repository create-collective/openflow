"""The first layer must arm every module bay: a profile or an explicit "disabled".

Layer 0 is where a module profile is pulled to both sides of the board and what every other
layer inherits; a gap there leaves that module unconfigured on the keyboard. The planner reports
the gaps, the preview shows them, and the flash route refuses them unless told otherwise
(SCRUM-61, owner's rule 2026-09-16). No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import module_layout as ml   # noqa: E402

FULL = {"touch:keyboard_left": "cfg-touch", "touch:keyboard_right": "cfg-touch",
        "track:keyboard_left": "cfg-tl", "track:keyboard_right": "cfg-tr",
        "tune:keyboard_left": "cfg-tune", "tune:keyboard_right": "disabled",
        "float:keyboard_left": "disabled", "float:keyboard_right": "disabled"}


def test_a_complete_first_layer_has_no_gaps():
    assert ml.missing_base_bays(FULL) == []
    print("  every required bay armed (a profile or disabled): no gaps")


def test_missing_transparent_and_empty_all_count_as_gaps():
    bays = dict(FULL)
    del bays["touch:keyboard_right"]
    bays["tune:keyboard_left"] = "transparent"
    bays["track:keyboard_left"] = ""
    assert ml.missing_base_bays(bays) == ["track:keyboard_left", "tune:keyboard_left",
                                          "touch:keyboard_right"] or \
        set(ml.missing_base_bays(bays)) == {"touch:keyboard_right", "tune:keyboard_left",
                                            "track:keyboard_left"}
    assert ml.missing_base_bays({}) == list(ml.REQUIRED_BASE_BAYS)
    assert "float:keyboard_left" not in ml.missing_base_bays({}), "Float is not required"
    print("  absent, empty and transparent are gaps; float is never required")


def test_the_plan_carries_the_gaps_to_the_preview():
    """The DB flash path reports whatever the first layer leaves unarmed."""
    from test_flash_module_layout import _desired, BASE
    partial = {k: v for k, v in dict(BASE).items() if not k.startswith("touch")}
    _d, layout = _desired({0: partial, 1: {}, 2: {}})
    assert set(layout["baseBayGaps"]) == set(ml.missing_base_bays(partial))
    assert {"touch:keyboard_left", "touch:keyboard_right"} <= set(layout["baseBayGaps"])
    print("  apply_module_layout reports the first layer's gaps")
