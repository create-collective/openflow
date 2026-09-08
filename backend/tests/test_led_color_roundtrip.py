"""The LED colour preview in the browser must agree with the encoder, exactly.

`encode_led_record` is `[led][hue u16][SATURATION]`. The third byte is saturation, NOT brightness
-- brightness is a global device setting. An earlier version of this file asserted the opposite
with great confidence and pinned it across 274,881 colours, which is a good demonstration that
byte-agreement between two implementations of the same misunderstanding proves nothing about the
device. The correction came from flashing white in NayaFlow and reading the board back.

So white is (hue 0, sat 0) and round-trips EXACTLY; what the map cannot hold is brightness --
#808080 and #ffffff both store as (0, 0). The frontend has to reproduce
`keymap_read.hex_to_hue_sat` -> `keymap_read.hsv_to_hex` in JavaScript.

Two implementations of the same maths in two languages is a drift risk, and it is not
theoretical -- writing the JS produced three separate disagreements, every one of them a
last-bit float difference that no amount of reading the code would have shown:

  * reusing the frontend's own `hsvToHex` (same maths, c/x/m instead of colorsys's p/q/t)
    disagreed on #ffe500;
  * `(x + 1) % 1` to normalise a hue already in [0,1) rounds away the low bits -- 2479 colours;
  * `t = v*f` instead of colorsys's literal `v*(1-s*(1-f))` -- 81 colours.

Each landed on the far side of an exact .5 in the final round-to-255. So this test compares the
two implementations directly over a grid of the colour cube rather than trusting either. It
skips rather than fails when node is unavailable, because a missing toolchain is not a defect.
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
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device.keymap_read import hex_to_hue_sat, hsv_to_hex   # noqa: E402

_COLOR_JS = _BACKEND.parents[0] / "frontend" / "src" / "lib" / "color.js"

# The exact colours that caught each bug above. If a refactor reintroduces one of them, these
# name it rather than leaving a count to be re-derived.
REGRESSIONS = ["#ffe500", "#000420", "#0004a0", "#000c20", "#001080", "#ffffff", "#808080"]


def _grid():
    steps = list(range(0, 256, 8)) + [255]
    for r in steps:
        for g in steps:
            for b in steps:
                yield "#%02x%02x%02x" % (r, g, b)
    for n in range(256):                       # every grey: saturation 0 is the interesting edge
        yield "#%02x%02x%02x" % (n, n, n)
    yield from REGRESSIONS


def test_white_is_saturation_zero_and_round_trips_exactly():
    """The whole correction in three lines. This used to assert white -> red."""
    assert hex_to_hue_sat("#ffffff") == (0, 0)
    assert hsv_to_hex(0, 0) == "#ffffff"
    assert hex_to_hue_sat("#ff0000") == (0, 100)


def test_brightness_is_what_the_map_actually_loses():
    """Grey and white are indistinguishable on the device: there is no per-key brightness."""
    assert hex_to_hue_sat("#808080") == hex_to_hue_sat("#ffffff") == (0, 0)
    assert hex_to_hue_sat("#800000") == hex_to_hue_sat("#ff0000") == (0, 100)


def test_the_real_colours_naya_flashed_decode_as_captured():
    """Read off the board after a NayaFlow flash on 2026-09-08, cross-checked against NayaFlow's
    own database. These are the numbers that settled the question."""
    for hexv, expected in [("#ffffff", (0, 0)), ("#ff0000", (0, 100)), ("#0000ff", (240, 100)),
                           ("#ff6f00", (26, 100)), ("#00ff11", (124, 100)), ("#21ffaa", (157, 87)),
                           ("#00ff5e", (142, 100)), ("#6f00ff", (266, 100))]:
        assert hex_to_hue_sat(hexv) == expected, hexv


def test_hue_is_truncated_not_rounded():
    """#0084ff is hue 208.94. The device stores 208, so this truncates -- and it does the
    arithmetic on raw 0-255 ints, because a 0..1 float round trip reintroduces the off-by-one."""
    assert hex_to_hue_sat("#0084ff") == (208, 100)


def test_the_javascript_preview_matches_the_python_encoder(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    colors = list(_grid())
    expected = [[c, *hex_to_hue_sat(c)] for c in colors]
    expected = [[c, h, s, hsv_to_hex(h, s)] for c, h, s in expected]

    (tmp_path / "in.json").write_text(json.dumps(colors), encoding="utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(
        "import { hexToHueSat, hueSatToHex } from %s;\n"
        "import { readFileSync } from 'fs';\n"
        "const out = JSON.parse(readFileSync(%s,'utf8')).map((c) => {\n"
        "  const [h, s] = hexToHueSat(c);\n"
        "  return [c, h, s, hueSatToHex(h, s)];\n"
        "});\n"
        "process.stdout.write(JSON.stringify(out));\n"
        % (json.dumps(_COLOR_JS.as_uri()), json.dumps((tmp_path / "in.json").as_posix())),
        encoding="utf-8")

    proc = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)

    mismatches = [(e, g) for e, g in zip(expected, got) if e != g]
    assert not mismatches, (
        f"{len(mismatches)} of {len(expected)} colours differ between the JS preview and the "
        f"Python encoder; first five: {mismatches[:5]}")


def test_the_preview_helper_is_actually_exported():
    """The test above imports the two primitives; the UI calls deviceColor. Pin that it exists,
    so a rename cannot leave this suite green while the page imports nothing."""
    src = _COLOR_JS.read_text(encoding="utf-8")
    for name in ("export function hexToHueSat", "export function hueSatToHex",
                 "export function deviceColor"):
        assert name in src, name
