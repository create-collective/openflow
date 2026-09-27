"""The keyboard's battery reads 100% when it is full, whatever firmware it runs.

The keyboard reports its cell voltage and nothing else; the percentage is ours (NayaFlow shows no
keyboard percentage at all, only the voltage on its diagnostics page). It used the module's straight
3.3-4.2 V line, and on the owner's boards (2026-09-26, both on USB, flat for 30 minutes) 3.28.7 holds
the cell at ~4.2 V while 3.41.0 holds it at ~4.07-4.10 V -- so every board on newer firmware "topped
out" at 85-88%, which testers reported as a worn battery. 3.35.4 read low too; only 3.28.7 has read
full. The keyboard now reads a lithium-ion curve scaled to where its firmware's charger stops.
Modules keep NayaCore's own linear formula, so they read what NayaFlow shows. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device.service import (  # noqa: E402
    _battery_percent, _keyboard_battery_percent as kb)


def test_a_full_board_on_newer_firmware_reads_full():
    """The owner's 3.41.0 halves, full on USB: 4091 and 4067 mV, 4061 at the lowest sample."""
    for mv in (4091, 4067, 4061):
        assert kb(mv, "3.41.0") == 100, mv


def test_the_boundary_is_after_3_28_7():
    """3.28.7 charges to 4.2 V; from 3.30 on (3.31.1, 3.35.4, 3.41.0) the charger stops near 4.1 V."""
    assert kb(4067, "3.35.4") == 100
    assert kb(4067, "3.31.1") == 100
    assert kb(4206, "3.28.7") == 100
    assert kb(4067, "3.28.7") < 90, "a 4.2 V board at 4.07 V is not full"


def test_unknown_firmware_keeps_the_4_2_volt_point():
    assert kb(4200, None) == 100
    assert kb(4091, None) < 90


def test_the_curve_is_lithium_shaped_and_monotonic():
    """3.7 V is nearly empty for a lithium cell; a straight line called it 44%."""
    assert kb(3700, "3.41.0") <= 20
    assert kb(3270, "3.41.0") == 1 and kb(3000, "3.41.0") == 1
    for fw in ("3.28.7", "3.41.0"):
        prev = 0
        for mv in range(3200, 4300, 5):
            p = kb(mv, fw)
            assert 1 <= p <= 100 and p >= prev, (fw, mv, p, prev)
            prev = p


def test_modules_keep_nayacores_linear_formula():
    """So a module reads the same percentage here as in NayaFlow."""
    assert _battery_percent(4200) == 100 and _battery_percent(3750) == 50 and _battery_percent(3300) == 1
