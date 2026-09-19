"""Does a cached deep status describe the keyboard that is attached NOW? (SCRUM-87)

The Devices page paints from a cached deep read and only re-reads on a click, so swapping
keyboards left it reporting the previous board's ports, serials, BLE addresses and modules --
two days stale in the observed case -- while the profile bar above it was correct. Nothing tied
the cached row to the hardware it came from, so it had no way to notice.

Answered by SERIAL against USB enumeration, which needs no serial I/O: asking the keyboard would
defeat the point of a cache that exists to avoid exactly that.

The three-valued answer is the part worth pinning. None means "cannot tell" and must not be
rendered as a mismatch -- older firmware really does report no serial, and accusing a correct
page of describing the wrong keyboard is worse than saying nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest  # noqa: E402

LEFT, RIGHT = "42A44FE4776195CB", "8A981891D384A036"
OTHER_L, OTHER_R = "B269FA744772B9E1", "4792220EA9D09F07"


@pytest.fixture
def attached(monkeypatch):
    """Point the helper at a chosen set of enumerated serials."""
    def use(*serials):
        svc = SimpleNamespace(
            visible_ports=lambda: [SimpleNamespace(serial_number=s) for s in serials])
        monkeypatch.setattr(rest, "get_service", lambda: svc)
    return use


def cached(*serials):
    return {"halves": [{"serialNumber": s} for s in serials]}


def test_the_same_keyboard_matches(attached):
    attached(LEFT, RIGHT)
    assert rest._cache_matches_attached(cached(LEFT, RIGHT)) is True


def test_a_different_keyboard_does_not(attached):
    """The reported case: the page was describing the board that had been unplugged."""
    attached(OTHER_L, OTHER_R)
    assert rest._cache_matches_attached(cached(LEFT, RIGHT)) is False


def test_swapping_one_half_still_counts_as_matching(attached):
    """A partial overlap is not 'a different keyboard'. The half still attached IS described,
    and calling the whole reading foreign would be the more misleading answer."""
    attached(LEFT, OTHER_R)
    assert rest._cache_matches_attached(cached(LEFT, RIGHT)) is True


def test_nothing_on_usb_is_reported_as_disconnected(attached):
    """Unplugging everything makes the reading OLD, not WRONG -- it is not a DIFFERENT keyboard,
    so it must not be reported as one. But a page listing ports and modules for hardware that is
    gone needs to say so, which is why this is its own answer rather than silence."""
    attached()
    assert rest._cache_matches_attached(cached(LEFT, RIGHT)) == "disconnected"


def test_disconnected_is_not_confused_with_a_mismatch(attached):
    """The two states read very differently to a user and must not collapse into each other."""
    attached()
    gone = rest._cache_matches_attached(cached(LEFT))
    attached(OTHER_L)
    foreign = rest._cache_matches_attached(cached(LEFT))
    assert gone == "disconnected" and foreign is False


def test_a_cache_without_serials_cannot_be_judged(attached):
    """Older firmware reports no serial. Unknown must stay unknown rather than become a warning
    on a page that is, as far as anyone can tell, correct."""
    attached(LEFT)
    assert rest._cache_matches_attached({"halves": [{"serialNumber": None}]}) is None
    assert rest._cache_matches_attached({"halves": []}) is None
    assert rest._cache_matches_attached({}) is None


def test_enumeration_failing_says_nothing(attached, monkeypatch):
    """A USB enumeration error must not be reported to the user as a hardware mismatch."""
    def boom():
        raise OSError("enumeration failed")
    monkeypatch.setattr(rest, "get_service",
                        lambda: SimpleNamespace(visible_ports=boom))
    assert rest._cache_matches_attached(cached(LEFT)) is None
