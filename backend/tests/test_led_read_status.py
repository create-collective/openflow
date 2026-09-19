"""An unrecognised response flag must not read as "no data" (SCRUM-94).

`read_full` continued only while the flag was 0x01 and stopped otherwise, so every other value
ended the read silently with whatever had been collected. On Create 3.28.7 the LED map answers
0x16 with a header-only frame, which arrived as an empty map indistinguishable from a board that
genuinely stores none.

That matters because a flash uses this read as its preservation baseline: LEDs the app has no
model for are carried through from what the board reports. An unreadable answer mistaken for an
empty map would silently drop module LED state on every flash.

The flag values are not invented here. They were established on the donor by probing, and the
last two were separated by WRITING a map to the layer and watching the very same read start
returning records.
"""
from openflow_backend.device import keymap_read as KR


class Frame:
    def __init__(self, flags, payload):
        self.flags, self.payload, self.valid = flags, bytes(payload), True


def test_the_donor_case_is_reported_as_empty_not_as_a_mystery():
    """0x16 with only the layer byte: the board says it has no map, and we believe it."""
    assert KR.chunk_status(b"", 0x16) == "empty"
    assert KR.chunk_status(b"", 0x18) == "empty"


def test_a_flag_we_do_not_know_is_reported_as_such():
    """The whole point: never again turn an unfamiliar answer into a confident empty map."""
    assert KR.chunk_status(b"", 0x42) == "unknown:0x42"
    assert KR.chunk_status(b"", 0x99) == "unknown:0x99"


def test_an_unimplemented_command_is_distinguished():
    assert KR.chunk_status(b"", KR.RESP_UNIMPLEMENTED) == "unsupported"


def test_silence_is_distinguished_from_an_answer():
    assert KR.chunk_status(b"", None) == "silent"


def test_a_normal_empty_answer_is_still_empty():
    assert KR.chunk_status(b"", KR.RESP_LAST) == "empty"


def test_records_win_over_any_flag():
    """If the board sent data, how it flagged the last chunk does not make it unreadable."""
    assert KR.chunk_status(b"\x00\x01\x02\x03", 0x42) == "ok"


# --- through the real reader --------------------------------------------------------------

class FakeTransport:
    """Answers READ_LED_MAP per layer from a script; everything else answers empty.

    The frame is parsed rather than indexed from the end, because the last bytes are a
    checksum: the data region is [subcmd hi][subcmd lo][flags][payload], so the layer byte
    sits three after the subcommand.
    """

    SUBS = (KR.READ_LAYER_LIST, KR.READ_LAYER_DATA, KR.READ_LED_MAP)

    def __init__(self, led_by_layer):
        self.led = led_by_layer

    @classmethod
    def _parse(cls, frame):
        for i in range(len(frame) - 1):
            sub = (frame[i] << 8) | frame[i + 1]
            if sub in cls.SUBS:
                payload = frame[i + 3:]
                return sub, (payload[0] if payload else 0)
        return 0, 0

    def _send_raw(self, frame, timeout=2.0):
        sub, layer = self._parse(frame)
        if sub == KR.READ_LED_MAP:
            flags, body = self.led[layer]
            return [Frame(flags, bytes([layer]) + body)]
        if sub == KR.READ_LAYER_LIST:
            # One entry: [idx][id][animation][len=0x10][uuid16], after a one-byte header.
            entry = bytes([0, 0, 0, 0x10]) + bytes(16)
            return [Frame(KR.RESP_LAST, bytes([0]) + entry)]
        return [Frame(KR.RESP_LAST, bytes([layer]))]


def _read(led_by_layer):
    return KR.read_keymap(FakeTransport(led_by_layer), 0x50)


def test_read_keymap_reports_per_layer_status():
    got = _read({0: (0x16, b"")})
    assert got["led_status"][0] == "empty"
    assert got["led"][0] == []


def test_read_keymap_flags_an_answer_it_cannot_read():
    got = _read({0: (0x42, b"")})
    assert got["led_status"][0] == "unknown:0x42", \
        "an empty map from an unfamiliar flag must be reported, not asserted as fact"


def test_a_layer_with_real_records_reads_ok():
    body = b"".join(bytes([i, 0xab, 0x00, 100]) for i in range(4))
    got = _read({0: (0x00, body)})
    assert got["led_status"][0] == "ok"
    assert len(got["led"][0]) == 4


def test_existing_keys_are_unchanged():
    """Nothing that consumes the read has to change; the status is additive."""
    got = _read({0: (0x16, b"")})
    for key in ("layers", "led", "layer_uuids", "layer_animations", "bays"):
        assert key in got
