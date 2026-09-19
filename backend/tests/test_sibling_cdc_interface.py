"""A half that presents two live CDC interfaces (SCRUM-90).

Create 3.28.7 exposes two CDC interfaces per half, both enumerated, both healthy, sharing a
serial number, and only one of them answers. Which one is not predictable: on the donor the
right half answers MI_02 and the left MI_03, neither MI_00.

Two behaviours are pinned here:

  * the interface we are not using is not called "stale" unless it was tried and failed, and
  * an operation falls through to the sibling rather than failing on a healthy board.

Both are firmware-agnostic. The single-port cases below stand in for 3.41, the supported
baseline, and assert that nothing about it changed.
"""
import pytest

from openflow_backend._vendor.nayactl.transport import TransportError
from openflow_backend.device import port_access
from openflow_backend.device.service import DeviceService


class FakeDev:
    def __init__(self, port, side, serial, pid=0x0064):
        self.port, self.side, self.serial_number, self.pid = port, side, serial, pid
        self.description = f"USB Serial Device ({port})"


LEFT_SN, RIGHT_SN = "B269FA744772B9E1", "4792220EA9D09F07"

# The donor, exactly as enumerated: the answering interface is COM23 on the left and COM22 on
# the right, so on each half it is a different one, and on the right it sorts SECOND by name.
DONOR = [FakeDev("COM21", "right", RIGHT_SN, 0x00C8), FakeDev("COM22", "right", RIGHT_SN, 0x00C8),
         FakeDev("COM23", "left", LEFT_SN), FakeDev("COM24", "left", LEFT_SN)]
ANSWERS = {"COM22", "COM23"}


def _svc(devices, answers, monkeypatch):
    svc = DeviceService()
    monkeypatch.setattr(svc, "visible_ports", lambda: list(devices))
    opened = []

    def fake_transport_for(port, dest):
        opened.append(port)
        if port in answers:
            svc._note_port(port, True)
            return f"transport:{port}"
        svc._note_port(port, False)
        raise TransportError("Keyboard did not respond to handshake. "
                             "Is it connected and powered on?")

    monkeypatch.setattr(svc, "_transport_for", fake_transport_for)
    return svc, opened


# --- B: the fallback ---------------------------------------------------------------------

def test_falls_through_to_the_sibling_that_answers(monkeypatch):
    """The cold-start case. COM21 sorts first by name and is deaf; COM22 is the live one."""
    svc, opened = _svc(DONOR, ANSWERS, monkeypatch)
    dev, t = svc._connect_side("right")
    assert opened == ["COM21", "COM22"], "should try the dead one, then its sibling"
    assert (dev.port, t) == ("COM22", "transport:COM22")


def test_the_half_that_already_sorts_right_opens_nothing_extra(monkeypatch):
    svc, opened = _svc(DONOR, ANSWERS, monkeypatch)
    dev, _t = svc._connect_side("left")
    assert opened == ["COM23"], "no sibling should be opened when the first port answers"
    assert dev.port == "COM23"


def test_the_fallback_happens_once_then_the_good_port_is_preferred(monkeypatch):
    svc, opened = _svc(DONOR, ANSWERS, monkeypatch)
    svc._connect_side("right")
    opened.clear()
    svc._connect_side("right")
    assert opened == ["COM22"], "_port_health should rank the live interface first from now on"


def test_a_lone_port_behaves_exactly_as_before(monkeypatch):
    """3.41: one interface per half. Nothing to fall back to, and the error is unchanged."""
    svc, opened = _svc([FakeDev("COM9", "left", LEFT_SN)], set(), monkeypatch)
    with pytest.raises(TransportError, match="did not respond to handshake"):
        svc._connect_side("left")
    assert opened == ["COM9"]


def test_never_crosses_to_a_different_keyboard(monkeypatch):
    """Two Creates attached: both have a 'left'. A fallback must not reach the other one."""
    other = FakeDev("COM31", "left", "OTHERKEYBOARD0001")
    svc, opened = _svc([FakeDev("COM30", "left", LEFT_SN), other], {"COM31"}, monkeypatch)
    with pytest.raises(TransportError):
        svc._connect_side("left")
    assert opened == ["COM30"], "a different serial is a different keyboard, never a sibling"


def test_no_serial_means_no_fallback(monkeypatch):
    """Without a serial nothing proves the two ports are one unit, so we do not guess."""
    svc, opened = _svc([FakeDev("COM40", "left", None), FakeDev("COM41", "left", None)],
                       {"COM41"}, monkeypatch)
    with pytest.raises(TransportError):
        svc._connect_side("left")
    assert opened == ["COM40"]


def test_permission_denied_is_not_retried_on_the_sibling(monkeypatch):
    """Linux without the udev rule: every sibling fails the same way. Say so once."""
    svc = DeviceService()
    monkeypatch.setattr(svc, "visible_ports", lambda: list(DONOR))
    opened = []

    def denied(port, dest):
        opened.append(port)
        raise port_access.PortAccessDenied(port)

    monkeypatch.setattr(svc, "_transport_for", denied)
    with pytest.raises(port_access.PortAccessDenied):
        svc._connect_side("right")
    assert opened == ["COM21"]


def test_released_is_not_treated_as_a_deaf_port(monkeypatch):
    """Releasing is our own decision; it must not send us hunting through siblings."""
    svc = DeviceService()
    monkeypatch.setattr(svc, "visible_ports", lambda: list(DONOR))
    opened = []

    def released(port, dest):
        opened.append(port)
        raise TransportError(svc.RELEASED_ERROR)

    monkeypatch.setattr(svc, "_transport_for", released)
    with pytest.raises(TransportError, match="released"):
        svc._connect_side("right")
    assert opened == ["COM21"]


# --- A: what counts as a stale port ------------------------------------------------------

def test_an_untried_sibling_is_not_stale(monkeypatch):
    svc, _opened = _svc(DONOR, ANSWERS, monkeypatch)
    assert svc._proved_dead(["COM21"]) == [], "nothing has tried it, so it says nothing"


def test_a_live_sibling_is_not_stale(monkeypatch):
    svc, _opened = _svc(DONOR, ANSWERS, monkeypatch)
    svc._connect_side("left")                      # proves COM23 good
    assert svc._proved_dead(["COM23"]) == []


def test_a_port_that_was_tried_and_failed_is_stale(monkeypatch):
    """The SCRUM-82 ghost: it gets tried, it fails, and it still earns the warning."""
    svc, _opened = _svc(DONOR, ANSWERS, monkeypatch)
    svc._connect_side("right")                     # tries COM21, which is deaf
    assert svc._proved_dead(["COM21", "COM22"]) == ["COM21"]


# --- the Devices page: status_all must use the same fallback ------------------------------

def _status_svc(monkeypatch):
    svc, opened = _svc(DONOR, ANSWERS, monkeypatch)
    monkeypatch.setattr(svc, "_query_half", lambda t, dest, deep=False, owner=None: {})
    return svc, opened


def test_status_reports_a_half_reached_through_its_sibling_as_connected(monkeypatch):
    """Before the fix this said connected=False on a perfectly healthy board."""
    svc, _opened = _status_svc(monkeypatch)
    right = [h for h in svc.status_all() if h["side"] == "right"][0]
    assert right["connected"] is True
    assert right["port"] == "COM22", "report the port we actually reached it on"


def test_an_untouched_sibling_is_never_called_stale(monkeypatch):
    """The left half answers on the first port, so its sibling is never opened or judged."""
    svc, _opened = _status_svc(monkeypatch)
    left = [h for h in svc.status_all() if h["side"] == "left"][0]
    assert left["stalePorts"] == []


def test_a_sibling_we_fell_through_is_still_reported(monkeypatch):
    """Current behaviour, pinned so that changing it has to be deliberate.

    Reaching the right half meant opening COM21 first and having it refuse the handshake, so it
    is reported as a port we PROVED dead. Whether that still deserves a user-facing warning once
    the fallback has already recovered from it is an open product question, not a correctness
    one: the half is connected either way.
    """
    svc, _opened = _status_svc(monkeypatch)
    right = [h for h in svc.status_all() if h["side"] == "right"][0]
    assert right["connected"] is True
    assert right["stalePorts"] == ["COM21"]


def test_the_port_we_settled_on_never_appears_in_its_own_stale_list(monkeypatch):
    svc, _opened = _status_svc(monkeypatch)
    for h in svc.status_all():
        assert h["port"] not in h["stalePorts"]
