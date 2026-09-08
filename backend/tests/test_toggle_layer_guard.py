"""Toggle Layer must not be bindable to a layer it cannot reach.

THE BUG IT PREVENTS. `&tog 0` toggles the base layer, which does NOT deactivate the layer you are
standing on. So a "back to base" key bound as Toggle works outward to layers 1 and 2 and never
back, and the keyboard is stuck until it is power-cycled. The device owner hit this on their own
board; every return key on it was `tog 0`.

NAYAFLOW FORBIDS THE SAME BINDING, which is what settles that this is a real constraint and not
our theory. Its renderer drops the first entry from the target list for this action type only:

    t.actionType === "layer_polite_toggle" && (l = l.toSpliced(0, 1))

(vendor-analysis/nayaflow/dist/renderer/assets/index-mihUmo_8.js). You cannot bind toggle-to-base
in NayaFlow at all. Force Layer keeps the base layer in its list, which is why it is the one that
can return you.

TWO RULES, WITH DIFFERENT EVIDENCE, and the difference is deliberate:
  * target is the BASE layer -> blocked. Measured: NayaFlow blocks it and the owner's board
    demonstrated the failure.
  * target is a LOWER layer -> blocked, because the layer you are on sits above it and hides it.
    NayaFlow permits this one; we reasoned it out rather than measuring it, so the copy says
    what to do instead rather than merely refusing.
  * target is the layer you are ON -> ALLOWED. `&tog N` from layer N turns that layer off, which
    is the ordinary "press the same key to come back" idiom, and neither rule above covers it.

The guard is JavaScript, so this shells out to node the same way test_led_color_roundtrip does.
It skips rather than fails when node is missing.
No hardware.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_PALETTE = _BACKEND.parents[0] / "frontend" / "src" / "components" / "ActionPalette.jsx"

# (actionType, targetIndex, currentIndex, expect_blocked, why)
CASES = [
    ("layer_polite_toggle", 0, 1, True,  "toggle to base from layer 1 -- the owner's actual bug"),
    ("layer_polite_toggle", 0, 2, True,  "toggle to base from layer 2"),
    ("layer_polite_toggle", 0, 0, True,  "toggle to base while on base"),
    ("layer_polite_toggle", 1, 2, True,  "downward: layer 2 hides layer 1"),
    ("layer_polite_toggle", 2, 1, False, "upward is what toggle is for"),
    ("layer_polite_toggle", 3, 0, False, "upward from base"),
    ("layer_polite_toggle", 2, 2, False, "SELF toggle -- the way back, must stay allowed"),
    ("layer_polite_toggle", 1, 1, False, "self toggle on layer 1"),
    ("layer_rude_toggle",   0, 2, False, "Force Layer to base is the recommended fix"),
    ("layer_polite_hold",   0, 2, False, "Hold Layer is unaffected"),
    ("layer_polite_oneshot", 0, 2, False, "Sticky Layer is unaffected"),
    ("layer_polite_toggle", 2, None, False, "unknown current layer: only the base rule applies"),
    ("layer_polite_toggle", 0, None, True,  "unknown current layer: base is still refused"),
]


def _run_guard(cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    src = _PALETTE.read_text(encoding="utf-8")
    start = src.index("export function toggleBlock")
    end = src.index("export default")
    body = src[start:end].replace("export function", "function", 1)
    script = (body + "\nconst out = " + json.dumps([c[:3] for c in cases])
              + ".map(([t, tgt, cur]) => toggleBlock(t, tgt, cur));\n"
              "process.stdout.write(JSON.stringify(out));\n")
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_guard_source_still_exists_where_the_test_looks_for_it():
    src = _PALETTE.read_text(encoding="utf-8")
    assert "export function toggleBlock" in src
    assert "currentLayerIndex" in src, "the palette must receive the layer being edited"


def test_every_case_blocks_or_allows_as_intended():
    results = _run_guard(CASES)
    wrong = []
    for (atype, tgt, cur, expect, why), got in zip(CASES, results):
        blocked = got is not None
        if blocked != expect:
            wrong.append(f"{why}: expected {'blocked' if expect else 'allowed'}, got "
                         f"{'blocked' if blocked else 'allowed'} ({got})")
    assert not wrong, "\n".join(wrong)


def test_a_refusal_says_what_to_do_instead():
    """A guard that only says no sends someone back to the same broken binding."""
    results = _run_guard(CASES)
    for (_a, _t, _c, expect, why), got in zip(CASES, results):
        if expect:
            assert "Force Layer" in got, f"{why}: {got!r} does not name the alternative"


def test_the_base_layer_rule_does_not_depend_on_knowing_the_current_layer():
    """The palette can be opened without a layer context; the measured rule must still hold."""
    assert _run_guard([("layer_polite_toggle", 0, None, True, "")])[0] is not None


def test_only_toggle_is_constrained():
    """Force Layer and Hold must stay bindable to anything -- Force Layer to base IS the fix."""
    others = [c for c in CASES if c[0] != "layer_polite_toggle"]
    assert all(r is None for r in _run_guard(others))
