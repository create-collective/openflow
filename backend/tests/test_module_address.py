"""The dock-bus address carries the module type AND the side it is docked on.

We first mapped types onto the two exact addresses we had seen -- 0x21 and 0x40 --
each captured with that module on one particular half. Moving either module to the
other half then reported "Unknown", because bit 0 of the address is the side, not
part of the type. Confirmed on hardware (fw 3.41.0) by swapping the same two
modules between halves:

    Track   0x20 left / 0x21 right
    Tune    0x40 left / 0x41 right
"""
import pytest

from openflow_backend._vendor.nayactl.constants import (
    module_side_from_address,
    module_type_from_address,
)

# (address, type, side) -- every combination observed on the real board.
OBSERVED = [
    (0x20, "Track", "left"),
    (0x21, "Track", "right"),
    (0x40, "Tune", "left"),
    (0x41, "Tune", "right"),
]


@pytest.mark.parametrize("addr,expected_type,expected_side", OBSERVED)
def test_type_and_side_survive_a_module_swap(addr, expected_type, expected_side):
    assert module_type_from_address(addr) == expected_type
    assert module_side_from_address(addr) == expected_side


def test_both_sides_of_a_module_resolve_to_one_type():
    """The regression itself: a module must not become Unknown by changing halves."""
    for left, right in ((0x20, 0x21), (0x40, 0x41)):
        assert module_type_from_address(left) == module_type_from_address(right)


def test_unknown_address_reports_the_number_rather_than_guessing():
    # Touch and Float are still uncaptured; a bug report needs to carry the address.
    assert module_type_from_address(0x60) == "Unknown (addr 0x60)"
    assert module_type_from_address(None) == "Unknown"
    assert module_side_from_address(None) is None
