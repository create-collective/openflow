"""Connections degrades instead of hard-failing on older firmware (SCRUM-91).

`ble_profiles` raised "the left half returned no Bluetooth status" whenever BLE_GET_STATUS went
unanswered, so a Create on 3.28.7 showed an error and nothing else, on a keyboard that pairs and
types perfectly well.

Probed on the donor, both halves agreeing: every BLE opcode from 0x100C up (GET_STATUS,
GET_DONGLE_ADDR, GET_SLOTX_ADDR, GET_FW_VERSION) goes unanswered while everything below answers
normally. So that firmware predates those commands rather than being faulty, and the identity
behind the slot view survives.

No test here checks a firmware version, because the code does not: the fallback is driven by the
command going unanswered.
"""
from openflow_backend._vendor.nayactl import constants as C
from openflow_backend._vendor.nayactl.transport import TransportError
from openflow_backend.device.service import DeviceService


class Frame:
    def __init__(self, payload):
        self.payload, self.valid, self.flags = bytes(payload), True, 0x00


ADDR = bytes.fromhex("d4a7940c4d98")
PEER = bytes.fromhex("f70bb6c5bbd1")


class Old:
    """A half with no BLE_GET_STATUS, answering everything below 0x100C, as measured."""
    port, side, serial_number = "COM23", "left", "B269FA744772B9E1"

    ANSWERS = {C.BLE_GET_ADDRESS: ADDR,
               C.BLE_GET_PAIR_ADDRESS: PEER,
               C.BLE_GET_ALL_PAIRS: bytes([1]) + PEER,
               C.BLE_GET_NAME: bytes([11]) + b"DefaultName"}

    def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
        if subcmd in self.ANSWERS:
            return [Frame(self.ANSWERS[subcmd])]
        return []                       # 0x100C and up: silence


def _svc(monkeypatch, transport):
    svc = DeviceService()
    monkeypatch.setattr(svc, "_connect_side", lambda side: (Old(), transport))
    monkeypatch.setattr(svc, "_dest_for_side", lambda side: 0x50)
    return svc


def test_it_no_longer_raises(monkeypatch):
    got = _svc(monkeypatch, Old()).ble_profiles("left")
    assert got["ok"] is True
    assert got["slotsAvailable"] is False


def test_it_reports_the_identity_the_half_can_still_give(monkeypatch):
    got = _svc(monkeypatch, Old()).ble_profiles("left")
    assert got["localAddress"] == "D4:A7:94:0C:4D:98"
    assert got["pairAddress"] == "F7:0B:B6:C5:BB:D1"
    assert got["pairedPeers"] == ["F7:0B:B6:C5:BB:D1"]
    assert got["name"] == "DefaultName"


def test_it_does_not_invent_slots(monkeypatch):
    """Which slot is active lives only in GET_STATUS. Unknown is reported, never guessed."""
    got = _svc(monkeypatch, Old()).ble_profiles("left")
    assert got["slots"] == []
    assert got["activeProfile"] is None
    assert got["hostConnected"] is None
    assert "firmware does not report Bluetooth slot status" in got["unavailableReason"]


def test_a_half_with_no_name_is_not_an_error(monkeypatch):
    """The right half answers flags 0xff with an empty payload; that is 'unset', not a fault."""
    class NoName(Old):
        ANSWERS = {k: v for k, v in Old.ANSWERS.items() if k != C.BLE_GET_NAME}

    got = _svc(monkeypatch, NoName()).ble_profiles("left")
    assert got["name"] is None
    assert got["ok"] is True


def test_a_half_that_answers_status_still_gets_the_full_view(monkeypatch):
    """The 3.41 baseline must be untouched: slots present, slotsAvailable true."""
    import openflow_backend.device.ble_status as ble_status

    class New(Old):
        def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
            if subcmd == C.BLE_GET_STATUS:
                return [Frame(b"\x01" * 40)]
            return super().send_command(dest, category, subcmd, payload, timeout)

    monkeypatch.setattr(ble_status, "decode",
                        lambda raw: {"activeProfile": 2, "hostConnected": True,
                                     "localAddress": "AA:BB:CC:DD:EE:FF",
                                     "profiles": [{"index": 0, "isActive": False,
                                                   "hasPeerData": False, "activeFlags": 0}]})
    got = _svc(monkeypatch, New()).ble_profiles("left")
    assert got["slotsAvailable"] is True
    assert got["activeProfile"] == 2
    assert len(got["slots"]) == 1


# --- one slot view, shared by the live read and the cached one -----------------------------

def test_slot_view_is_the_single_place_the_reserved_rule_lives():
    """Connections paints from the cached deep read now, so the shaping must not be duplicated.

    Slot 0 is never offered by NayaFlow's keys and is most likely the dongle's, so it is shown
    but not selectable. A second copy of that judgement in the frontend would be one too many.
    """
    decoded = {"profiles": [
        {"index": 0, "isActive": False, "hasPeerData": True, "activeFlags": 0},
        {"index": 1, "isActive": True, "hasPeerData": True, "connected": True,
         "peerAddress": "AA:BB:CC:DD:EE:FF", "activeFlags": 3},
        {"index": 2, "isActive": False, "hasPeerData": False, "activeFlags": 0},
    ]}
    slots = DeviceService.slot_view(decoded)
    assert [s["index"] for s in slots] == [0, 1, 2]
    assert [s["reserved"] for s in slots] == [True, False, False]
    assert slots[1]["active"] and slots[1]["connected"] and slots[1]["bonded"]
    assert slots[1]["peerAddress"] == "AA:BB:CC:DD:EE:FF"
    assert not slots[2]["bonded"], "nothing paired there"


def test_the_live_read_and_the_shared_shaper_agree(monkeypatch):
    """ble_profiles must go through slot_view, not keep a copy of it."""
    import openflow_backend.device.ble_status as ble_status

    decoded = {"activeProfile": 1, "hostConnected": True, "localAddress": "AA:BB:CC:DD:EE:FF",
               "profiles": [{"index": 0, "isActive": False, "hasPeerData": False,
                             "activeFlags": 0}]}

    class New(Old):
        def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
            if subcmd == C.BLE_GET_STATUS:
                return [Frame(b"\x01" * 40)]
            return super().send_command(dest, category, subcmd, payload, timeout)

    monkeypatch.setattr(ble_status, "decode", lambda raw: decoded)
    got = _svc(monkeypatch, New()).ble_profiles("left")
    assert got["slots"] == DeviceService.slot_view(decoded)
