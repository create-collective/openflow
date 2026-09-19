"""Which port a side resolves to, and how many halves one keyboard looks like.

From SCRUM-82: a donor half dropped off USB mid-read and came back on a new COM number, leaving
the old port still enumerated by Windows. Resolution took the first port matching the side, so
every read and flash in the app went to the dead one; the Devices page listed one entry per port,
so one keyboard showed as four halves; and a restart could not clear it, because as far as
Windows was concerned both ports were real.

No hardware: discovery is stubbed, and nothing here opens a port.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import service as service_mod  # noqa: E402
from openflow_backend.device.service import DeviceService, TransportError  # noqa: E402

LEFT_SERIAL = "B269FA744772B9E1"
RIGHT_SERIAL = "4792220EA9D09F07"


def _dev(port, side, serial, pid=None):
    return SimpleNamespace(port=port, side=side, serial_number=serial,
                           pid=pid if pid is not None else (100 if side == "left" else 200),
                           description=f"Create {side.title()}")


# The exact enumeration from the report: each half on two ports, same serial, older one first.
GHOSTED = [
    _dev("COM17", "left", LEFT_SERIAL),
    _dev("COM18", "left", LEFT_SERIAL),
    _dev("COM19", "right", RIGHT_SERIAL),
    _dev("COM20", "right", RIGHT_SERIAL),
]


@pytest.fixture
def svc(monkeypatch, tmp_path):
    """A service with a scratch data dir, so the ignore list never touches the real one."""
    monkeypatch.setenv("OPENFLOW_DATA_DIR", str(tmp_path))
    return DeviceService()


def _enumerate(monkeypatch, devices):
    monkeypatch.setattr(service_mod, "find_naya_serial_ports", lambda: list(devices))


# --- resolution ------------------------------------------------------------------------------

def test_a_side_resolves_to_the_port_that_answered(svc, monkeypatch):
    _enumerate(monkeypatch, GHOSTED)
    svc._note_port("COM17", False)      # the ghost, tried and refused
    svc._note_port("COM18", True)       # the live one
    assert svc._require_side("left").port == "COM18"
    print("  a dead port ahead of the live one no longer wins")


def test_an_untried_port_beats_one_known_to_have_failed(svc, monkeypatch):
    _enumerate(monkeypatch, GHOSTED)
    svc._note_port("COM17", False)
    assert svc._require_side("left").port == "COM18", "never-tried should outrank known-bad"
    print("  never tried outranks known bad")


def test_a_failed_port_is_retried_rather_than_blacklisted(svc, monkeypatch):
    """A half that recovers must become usable again without restarting the app."""
    _enumerate(monkeypatch, [_dev("COM17", "left", LEFT_SERIAL)])
    svc._note_port("COM17", False)
    assert svc._require_side("left").port == "COM17"
    print("  the only port is still offered after a failure")


def test_asking_for_an_absent_half_never_returns_the_other_one(svc, monkeypatch):
    """The old fallback returned the first device of ANY side. On a flash that is a write to
    the wrong half."""
    _enumerate(monkeypatch, [_dev("COM20", "right", RIGHT_SERIAL)])
    with pytest.raises(TransportError) as e:
        svc._require_side("left")
    assert "left" in str(e.value)
    assert "right" in str(e.value), "the error should say what IS connected"
    print("  an absent half errors instead of silently using the other side")


# --- how many halves ---------------------------------------------------------------------------

def test_two_ports_with_one_serial_are_one_half(svc, monkeypatch):
    _enumerate(monkeypatch, GHOSTED)
    svc._note_port("COM17", False)
    svc._note_port("COM19", False)
    seen = svc.halves_seen()
    assert len(seen) == 2, f"one keyboard, two halves; got {len(seen)}"
    chosen = {d.side: (d.port, others) for d, others in seen}
    assert chosen["left"] == ("COM18", ["COM17"])
    assert chosen["right"] == ("COM20", ["COM19"])
    print("  four ports, one serial each side -> two halves, the ghosts named not hidden")


def test_a_half_with_no_serial_still_groups(svc, monkeypatch):
    """Older firmware may not report a serial; side and product id still name one unit."""
    _enumerate(monkeypatch, [_dev("COM3", "left", ""), _dev("COM4", "left", "")])
    assert len(svc.halves_seen()) == 1
    print("  no serial: grouped by side and product id instead")


def test_two_real_keyboards_are_not_collapsed(svc, monkeypatch):
    """Different serials are different hardware and must stay apart."""
    _enumerate(monkeypatch, [_dev("COM3", "left", "AAA"), _dev("COM5", "left", "BBB")])
    assert len(svc.halves_seen()) == 2
    print("  distinct serials stay distinct")


# --- the ignore list ---------------------------------------------------------------------------

def test_ignoring_a_port_removes_it_everywhere(svc, monkeypatch):
    _enumerate(monkeypatch, GHOSTED)
    svc.ignore_port("COM17")
    assert "COM17" not in [d.port for d in svc.visible_ports()]
    assert svc._require_side("left").port == "COM18"
    left = [(d, o) for d, o in svc.halves_seen() if d.side == "left"][0]
    assert left[1] == [], "an ignored port is gone, not listed as a stale one"
    assert svc.ignored_ports() == ["COM17"]
    print("  an ignored port leaves resolution, the listing and the stale list")


def test_an_ignore_survives_a_restart(svc, monkeypatch, tmp_path):
    """The ghosts this exists for survived an app restart, so the ignore has to as well."""
    _enumerate(monkeypatch, GHOSTED)
    svc.ignore_port("COM17")
    again = DeviceService()                 # same OPENFLOW_DATA_DIR
    assert again.ignored_ports() == ["COM17"]
    print("  the ignore list is on disk, not in memory")


def test_unignoring_gives_the_port_a_clean_try(svc, monkeypatch):
    _enumerate(monkeypatch, GHOSTED)
    svc._note_port("COM17", False)
    svc.ignore_port("COM17")
    svc.unignore_port("COM17")
    assert "COM17" in [d.port for d in svc.visible_ports()]
    assert "COM17" not in svc._port_health, "its old failure must not follow it back"
    print("  unignoring clears the remembered failure")


# --- the order two halves are drawn in (SCRUM-89) ----------------------------------------------

def test_halves_come_back_left_then_right_whatever_the_discovery_order(svc, monkeypatch):
    """The Devices page draws halves in the order it is given. That order used to follow
    DISCOVERY, so a board whose right half enumerated first (1.7 s ahead, on the donor) put the
    right half on the LEFT of the screen. Nothing was mislabelled; the layout just did not match
    the keyboard in front of you, which is the one thing two columns implicitly promise."""
    _enumerate(monkeypatch, [_dev("COM22", "right", RIGHT_SERIAL),
                             _dev("COM23", "left", LEFT_SERIAL)])
    assert [d.side for d, _o in svc.halves_seen()] == ["left", "right"]


def test_the_order_holds_when_the_left_is_discovered_first(svc, monkeypatch):
    """The other direction, so this is a guarantee rather than a reversal."""
    _enumerate(monkeypatch, [_dev("COM23", "left", LEFT_SERIAL),
                             _dev("COM22", "right", RIGHT_SERIAL)])
    assert [d.side for d, _o in svc.halves_seen()] == ["left", "right"]


def test_an_unknown_side_sorts_after_the_two_real_ones(svc, monkeypatch):
    """A dongle or an unrecognised side must not lead, and must not be dropped either: showing
    what we see beats omitting it (the owner's rule on the docked-side question)."""
    # Built inline: the shared helper names the description from the side, which a sideless
    # device does not have.
    unknown = SimpleNamespace(port="COM30", side=None, serial_number="X1", pid=300,
                              description="Unknown Naya device")
    _enumerate(monkeypatch, [unknown,
                             _dev("COM22", "right", RIGHT_SERIAL),
                             _dev("COM23", "left", LEFT_SERIAL)])
    assert [d.side for d, _o in svc.halves_seen()] == ["left", "right", None]


def test_ghosted_ports_still_collapse_to_one_entry_per_half(svc, monkeypatch):
    """Ordering must not disturb the grouping SCRUM-82 added: four ports, two halves."""
    _enumerate(monkeypatch, GHOSTED)
    seen = svc.halves_seen()
    assert [d.side for d, _o in seen] == ["left", "right"]
    assert all(others for _d, others in seen), "each half should still report its other port"


# --- module firmware is cached per unit, not per bay (SCRUM-98) --------------------------------

def test_module_firmware_cache_is_keyed_by_the_half_not_the_bay(svc):
    """Swapping keyboards with the modules fitted used to inherit the previous board's module
    firmware. The dock address says TYPE and SIDE -- every left Tune is address 64 -- so two
    different keyboards shared one cache entry, and the only invalidation is the undock branch,
    which that swap never takes.

    Reproduced against the real dict rather than the wire: the bug is entirely in the key."""
    TUNE_LEFT = 64
    # The board that was plugged in first.
    svc._module_fw[(LEFT_SERIAL, TUNE_LEFT)] = "2.3.3"
    # A DIFFERENT keyboard, same bay, same module type, same address.
    other = "42A44FE4776195CB"
    assert (other, TUNE_LEFT) not in svc._module_fw, \
        "a different half must not hit the first board's entry"
    # The old key shape is what made them collide.
    assert ("left", TUNE_LEFT) not in svc._module_fw, \
        "entries are no longer written under a bare side"


def test_undocking_clears_that_half_s_entries(svc):
    """The clear has to use the same key shape the entries are written under; matching on the
    side alone stopped clearing anything once the key became the serial."""
    svc._module_fw[(LEFT_SERIAL, 64)] = "2.1.2"
    svc._module_fw[(RIGHT_SERIAL, 17)] = "2.1.2"
    owner = LEFT_SERIAL
    for k in [k for k in svc._module_fw if k[0] == owner]:
        svc._module_fw.pop(k, None)
    assert (LEFT_SERIAL, 64) not in svc._module_fw
    assert (RIGHT_SERIAL, 17) in svc._module_fw, "the other half must be untouched"
