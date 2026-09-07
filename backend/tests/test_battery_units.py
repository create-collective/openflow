"""Module battery voltages arrive in a different unit from the keyboard's.

The bug this pins: MODULE_GET_PRECISE_BATTERY reports plain millivolts (4152 = 4.152 V) despite
its name, while MODULE_GET_BATTERY reports tenths of a millivolt (41423) and the keyboard's own
SYS_GET_KB_BATTERY_LEVEL reports millivolts. The precise reading was fed straight into the
0.1 mV maths, so `max(33000, 4152)` clamped to the 3.3 V floor and EVERY module reported
exactly 1% battery while NayaFlow showed the same module at 95-100%.

Values below are real, captured back to back from the same modules on module firmware 2.3.3:

    Track   PRECISE 0x1038 = 4152 mV     GET_BATTERY 0xA1CF = 41423 (0.1 mV)
    Tune    PRECISE 0x108C = 4236 mV     GET_BATTERY 0xA64C = 42572 (0.1 mV)
"""
from openflow_backend.device.service import _battery_percent, _to_millivolts


def test_the_regression_a_full_module_is_not_one_percent():
    """The whole bug in one assertion."""
    assert _battery_percent(_to_millivolts(4152)) > 90


def test_both_units_agree_for_the_same_cell():
    """The two commands describe the same physical cell, so they must land on the same percent."""
    for precise_mv, tenth_mv in ((4152, 41423), (4236, 42572)):
        a = _battery_percent(_to_millivolts(precise_mv))
        b = _battery_percent(_to_millivolts(tenth_mv))
        assert abs(a - b) <= 1, f"{precise_mv} mV -> {a}%, {tenth_mv} (0.1 mV) -> {b}%"


def test_the_unit_sniff_boundary():
    """Sniffed, not blindly scaled -- no real cell reads below 1.0 V."""
    assert _to_millivolts(4152) == 4152        # millivolts, passed through
    assert _to_millivolts(41423) == 4142       # tenths, scaled down
    assert _to_millivolts(9999) == 9999        # still treated as mV
    assert _to_millivolts(10000) == 1000       # first value treated as tenths


def test_keyboard_readings_are_unchanged():
    """The keyboard path already worked; the shared helper must not move it."""
    assert _battery_percent(_to_millivolts(4200)) == 100
    assert _battery_percent(_to_millivolts(3300)) == 1
    assert _battery_percent(_to_millivolts(3750)) == 50


def test_percent_never_leaves_one_to_a_hundred():
    """A dead or over-reading cell must not render as -12% or 137%."""
    for mv in (0, 1, 2500, 3299, 4201, 5000, 65535):
        assert 1 <= _battery_percent(_to_millivolts(mv)) <= 100, mv


def test_nayaflow_calibration_points():
    """Cross-checked against NayaFlow showing the same Tune; floor-vs-round explains the 1%."""
    assert _battery_percent(_to_millivolts(4228)) == 100    # NayaFlow 100%
    assert abs(_battery_percent(_to_millivolts(4127)) - 92) <= 1   # NayaFlow 92%
