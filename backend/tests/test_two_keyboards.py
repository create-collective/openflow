"""Two physical Creates attached at once (SCRUM-86).

Everything in the poll assumed one keyboard: a half was identified by its SIDE, so "the left
half" meant something. With two Creates there are two legitimate lefts, and the assumption
failed in four places at once -- the status bar showed one left alternating between boards, one
keyboard's disconnect was never noticed, two boards' battery readings were folded together, and
the split-link verdict cross-compared halves that were never a pair.

Halves are joined into keyboards by BLE identity: a half whose pairAddress is the other's own
bleAddress. Verified with two boards attached, including one whose halves are on mismatched
firmware and cannot talk to each other -- the stored pairing RECORD survives even when the link
does not, which is exactly what makes the join reliable for diagnosing that failure.

The addresses below are the real ones from those two boards.
"""
import pytest

from openflow_backend.device.service import DeviceService, pairing_report

DONOR_L, DONOR_R = "D4:A7:94:0C:4D:98", "F7:0B:B6:C5:BB:D1"
WARR_L, WARR_R = "FA:4A:56:71:5F:51", "DD:DB:65:D1:46:CA"


def half(side, port, own, pair, fw="3.41.0", nested=False, **extra):
    h = {"side": side, "port": port, "bleAddress": own, "connected": True,
         "firmwareVersion": fw, **extra}
    if pair is not None:
        if nested:
            h["ble"] = {"pairAddress": pair}      # how a DEEP read carries it
        else:
            h["pairAddress"] = pair               # how the cheap poll carries it
    return h


def four():
    return [half("left", "COM23", DONOR_L, DONOR_R, "3.28.7"),
            half("left", "COM30", WARR_L, WARR_R, "3.41.0"),
            half("right", "COM22", DONOR_R, DONOR_L, "3.28.7"),
            half("right", "COM29", WARR_R, WARR_L, "3.35.4")]


# --- the join -------------------------------------------------------------------------------

def test_two_keyboards_are_told_apart():
    got = DeviceService.group_into_keyboards(four())
    ids = {h["port"]: h["keyboardId"] for h in got}
    assert ids["COM23"] == ids["COM22"], "the donor's halves are one keyboard"
    assert ids["COM30"] == ids["COM29"], "the warranty board's halves are one keyboard"
    assert ids["COM23"] != ids["COM30"], "and they are not the same keyboard"
    assert all(h["keyboardCount"] == 2 for h in got)


def test_halves_come_out_left_then_right_per_keyboard():
    """The page draws them in the order given; it should not have to sort for itself."""
    got = DeviceService.group_into_keyboards(four())
    for kid in {h["keyboardId"] for h in got}:
        sides = [h["side"] for h in got if h["keyboardId"] == kid]
        assert sides == ["left", "right"]


def test_a_deep_reads_nested_pair_address_is_accepted():
    """A reading cached before halves carried a keyboard must still group, without re-reading."""
    got = DeviceService.group_into_keyboards([
        half("left", "COM23", DONOR_L, DONOR_R, nested=True),
        half("right", "COM22", DONOR_R, DONOR_L, nested=True)])
    assert got[0]["keyboardId"] == got[1]["keyboardId"]
    assert got[0]["keyboardCount"] == 1


def test_a_one_sided_claim_is_not_a_keyboard():
    """Pairing on one half's say-so is how a flash gets aimed at the wrong board."""
    got = DeviceService.group_into_keyboards([
        half("left", "COM23", DONOR_L, WARR_R),        # points at a half that does not point back
        half("right", "COM22", DONOR_R, DONOR_L)])
    assert got[0]["keyboardId"] != got[1]["keyboardId"]


def test_a_half_with_no_partner_still_appears():
    """A half nobody can place is what someone chasing a broken keyboard needs to see."""
    got = DeviceService.group_into_keyboards([half("left", "COM23", DONOR_L, None)])
    assert len(got) == 1 and got[0]["keyboardCount"] == 1


def test_one_keyboard_is_unchanged():
    got = DeviceService.group_into_keyboards([
        half("left", "COM23", DONOR_L, DONOR_R), half("right", "COM22", DONOR_R, DONOR_L)])
    assert [h["keyboardId"] for h in got] == [0, 0]
    assert [h["keyboardCount"] for h in got] == [1, 1]


# --- the split-link verdict ------------------------------------------------------------------

def test_the_verdict_never_compares_halves_of_different_keyboards():
    """by_side kept only the LAST left and right, so two boards could be cross-compared and a
    healthy pair called broken -- on the one tab whose job is diagnosing that."""
    rep = pairing_report(DeviceService.group_into_keyboards(four()))
    assert len(rep["keyboards"]) == 2
    assert [k["state"] for k in rep["keyboards"]] == ["paired", "paired"]


def test_the_single_keyboard_shape_is_unchanged():
    """Every existing caller reads state/detail off the top level."""
    rep = pairing_report(DeviceService.group_into_keyboards([
        half("left", "COM23", DONOR_L, DONOR_R, nested=True),
        half("right", "COM22", DONOR_R, DONOR_L, nested=True)]))
    assert rep["state"] == "paired"
    assert "detail" in rep and len(rep["keyboards"]) == 1


# --- the poll's own state --------------------------------------------------------------------

class Dev:
    def __init__(self, port, side, serial):
        self.port, self.side, self.serial_number = port, side, serial
        self.description, self.pid = f"Create {side}", 0x0064


def test_the_half_key_is_the_serial_not_the_side():
    """self._live was keyed by side, so two lefts overwrote each other on every tick."""
    a, b = Dev("COM23", "left", "AAAA"), Dev("COM30", "left", "BBBB")
    assert DeviceService._half_key(a) != DeviceService._half_key(b)


def test_a_half_without_a_serial_falls_back_to_its_port():
    d = Dev("COM9", "left", None)
    assert DeviceService._half_key(d) == "COM9"


def test_unplugging_one_keyboard_is_noticed(monkeypatch):
    """tick_all built `seen` from SIDES, so with the other board still attached the side stayed
    'seen' and the disconnect went unreported entirely."""
    svc = DeviceService()
    svc._live = {
        "AAAA": {"side": "left", "port": "COM23", "connected": True},
        "BBBB": {"side": "left", "port": "COM30", "connected": True},
    }
    # Only the second keyboard's left is still on the bus.
    monkeypatch.setattr(svc, "halves_seen", lambda: [(Dev("COM30", "left", "BBBB"), [])])
    monkeypatch.setattr(svc, "tick", lambda dev: None)
    svc.tick_all()
    assert svc._live["AAAA"]["connected"] is False, "the unplugged keyboard must be marked gone"
    assert svc._live["BBBB"]["connected"] is True, "the attached one must be untouched"
