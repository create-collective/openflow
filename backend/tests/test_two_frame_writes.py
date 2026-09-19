"""No write may need a third CDC frame (SCRUM-100).

Create 3.28.7 hangs on a write whose byte-3 countdown starts at 0x02: the half stops answering
and stops typing until it is power-cycled. Proved on the donor, and isolated from the other
candidate cause -- a 120-record LED write reaching into the module blocks is two frames and is
completely fine, so it is the frame count and not the records.

A large payload is therefore delivered as several two-frame writes. These tests pin the two
properties that makes safe: the parts must reassemble to exactly the original bytes, and each
part must break on a RECORD boundary, never at a byte count.
"""
import pytest

from openflow_backend.device import flash as F
from openflow_backend.device import keymap_read as KR
from openflow_backend.device import remap as R


def led_payload(n):
    return R.encode_led_map(0, [R.encode_led_record(i, i % 360, 100) for i in range(n)])


def layer_payload(n, param_len=4):
    """n binding records of [key][behaviour][len][params]: variable length on purpose."""
    return R.encode_layer_data(2, [bytes([i, 0x01, param_len]) + bytes(param_len)
                                   for i in range(n)])


def op(sub, payload):
    return F.WriteOp(sub, payload, "thing")


def frames(o):
    return R.frames_for(0x50, o.sub, o.payload, cat=o.cat)


# --- the guarantee ------------------------------------------------------------------------

def test_the_full_led_map_no_longer_needs_three_frames():
    """136 records is 545 bytes, the exact write that wedged the donor."""
    before = op(R.WRITE_LED_MAP_DATA, led_payload(136))
    assert len(frames(before)) == 3, "precondition: this is the shape that hangs 3.28.7"
    parts = F.split_for_two_frames(before)
    assert len(parts) == 2
    assert all(len(frames(p)) <= 2 for p in parts)
    assert all(f[3] <= 1 for p in parts for f in frames(p)), "byte3 must never reach 0x02"


def test_a_payload_that_already_fits_is_untouched():
    """3.41 sends the same bytes it always did; nothing about the baseline changes."""
    small = op(R.WRITE_LED_MAP_DATA, led_payload(60))
    assert F.split_for_two_frames(small) == [small]


@pytest.mark.parametrize("n", [121, 136, 200, 400])
def test_led_parts_reassemble_to_exactly_the_original(n):
    original = led_payload(n)
    parts = F.split_for_two_frames(op(R.WRITE_LED_MAP_DATA, original))
    assert all(p.payload[:1] == original[:1] for p in parts), "each part re-sends the index byte"
    assert b"".join(p.payload[1:] for p in parts) == original[1:]


@pytest.mark.parametrize("param_len", [0, 1, 4, 7, 12])
def test_layer_parts_reassemble_to_exactly_the_original(param_len):
    original = layer_payload(90, param_len)
    parts = F.split_for_two_frames(op(R.WRITE_LAYER_DATA, original))
    assert b"".join(p.payload[1:] for p in parts) == original[1:]
    assert all(p.payload[:1] == original[:1] for p in parts)


def test_every_part_is_whole_records():
    """The point of splitting on boundaries: a torn record would write nonsense to a board."""
    original = layer_payload(120, 7)
    parts = F.split_for_two_frames(op(R.WRITE_LAYER_DATA, original))
    assert len(parts) > 1
    for p in parts:
        body = p.payload[1:]
        consumed = sum(3 + len(param) for _i, _t, param in KR.parse_records(body))
        assert consumed == len(body), "a part ended mid-record"


def test_records_are_not_duplicated_or_dropped():
    original = layer_payload(150, 5)
    parts = F.split_for_two_frames(op(R.WRITE_LAYER_DATA, original))
    seen = [r for p in parts for r in KR.parse_records(p.payload[1:])]
    assert seen == KR.parse_records(original[1:])
    assert len({idx for idx, _t, _p in seen}) == 150


def test_an_unparseable_payload_is_left_alone():
    """Guessing at boundaries could tear a record; leaving it is the safe failure."""
    ragged = op(R.WRITE_LED_MAP_DATA, bytes([0]) + bytes(601))   # 601 is not a multiple of 4
    assert F.split_for_two_frames(ragged) == [ragged]


def test_a_subcommand_we_cannot_parse_is_left_alone():
    big = op(R.WRITE_LAYER_LIST, bytes(600))
    assert F.split_for_two_frames(big) == [big]


def test_parts_are_labelled_so_the_preview_reads_honestly():
    parts = F.split_for_two_frames(op(R.WRITE_LED_MAP_DATA, led_payload(136)))
    assert [p.label for p in parts] == ["thing (part 1 of 2)", "thing (part 2 of 2)"]


def test_the_category_survives_the_split():
    o = F.WriteOp(R.WRITE_LAYER_DATA, layer_payload(120, 7), "thing", cat=R.CAT_REMAP)
    assert all(p.cat == R.CAT_REMAP for p in F.split_for_two_frames(o))
