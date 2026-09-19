"""Stop asking a half for BLE commands it has shown it does not have (SCRUM-91).

The deep read issues five BLE commands per half. On Create 3.28.7 three go unanswered -- every
opcode from 0x100C up -- so every Devices read burned three full timeouts per half, forever, for
nothing.

The cache keys on OBSERVED CAPABILITY, never on a firmware version, and carries the firmware in
the key so a version bump re-probes instead of inheriting an older build's answer. These tests
pin both halves of that.
"""
from openflow_backend._vendor.nayactl import constants as C
from openflow_backend.device.service import DeviceService


class Transport:
    """Answers the opcodes below 0x100C, like the donor; counts every send."""

    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def send_command(self, dest, category, subcmd, payload=b"", timeout=2.5):
        self.sent.append(subcmd)
        if subcmd in self.answers:
            class F:
                valid, flags = True, 0x00
                payload = b"\x01" * 6
            return [F()]
        return []


OLD = {C.BLE_GET_NAME, C.BLE_GET_PAIR_ADDRESS}          # 0x100C and up: silent
NEW = OLD | {C.BLE_GET_DONGLE_ADDR, C.BLE_GET_FW_VERSION, C.BLE_GET_STATUS}

KEY = ("B269FA744772B9E1", "3.28.7")


def asks(t, sub):
    return t.sent.count(sub)


def test_a_silent_command_is_asked_once_then_never_again():
    svc, t = DeviceService(), Transport(OLD)
    for _ in range(4):
        svc._ble_ask(t, 0x50, C.BLE_GET_STATUS, KEY)
    assert asks(t, C.BLE_GET_STATUS) == 1, "the timeout must be paid once, not every read"


def test_a_command_that_answers_is_always_asked():
    """Its value changes; only its EXISTENCE is cached."""
    svc, t = DeviceService(), Transport(OLD)
    for _ in range(4):
        assert svc._ble_ask(t, 0x50, C.BLE_GET_NAME, KEY) is not None
    assert asks(t, C.BLE_GET_NAME) == 4


def test_newer_firmware_on_the_same_half_is_probed_afresh():
    """The point of putting the firmware in the key: an update must not inherit this answer."""
    svc, t = DeviceService(), Transport(OLD)
    svc._ble_ask(t, 0x50, C.BLE_GET_STATUS, KEY)
    assert asks(t, C.BLE_GET_STATUS) == 1

    t2 = Transport(NEW)
    upgraded = (KEY[0], "3.41.0")
    assert svc._ble_ask(t2, 0x50, C.BLE_GET_STATUS, upgraded) is not None
    assert asks(t2, C.BLE_GET_STATUS) == 1, "re-probed under the new firmware, and it answered"


def test_two_keyboards_do_not_share_an_answer():
    svc, t = DeviceService(), Transport(OLD)
    svc._ble_ask(t, 0x50, C.BLE_GET_STATUS, KEY)
    other = Transport(NEW)
    assert svc._ble_ask(other, 0x50, C.BLE_GET_STATUS, ("OTHERBOARD0001", "3.41.0")) is not None


def test_a_half_that_answers_everything_is_never_skipped():
    """The 3.41 baseline: nothing is cached away, every command still goes out each time."""
    svc, t = DeviceService(), Transport(NEW)
    for _ in range(3):
        for sub in (C.BLE_GET_NAME, C.BLE_GET_DONGLE_ADDR, C.BLE_GET_STATUS):
            assert svc._ble_ask(t, 0x50, sub, ("X", "3.41.0")) is not None
    assert asks(t, C.BLE_GET_STATUS) == 3
    assert asks(t, C.BLE_GET_DONGLE_ADDR) == 3
