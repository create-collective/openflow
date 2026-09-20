"""Every flash ends with the full layer list, because that is what restores the lighting.

Measured on the board 2026-09-10 (docs/plan-status.md item 4): breathe engaged at runtime on
each half in turn; layer data, LED map and module writes leave it running; one WRITE_LAYER_LIST
byte-identical to the board's own table, sent to the left, drops BOTH halves back to the stored
animation and colours. NayaFlow's flash never did this because it only writes the list when a
layer is added or removed -- and neither did ours. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F                   # noqa: E402
from openflow_backend.device import remap as R                   # noqa: E402
from openflow_backend.device import service as S                 # noqa: E402

U0 = R.layer_uuid_bytes("0cb76a71-1d42-43c8-8b4e-ab1c521695c9")
U1 = R.layer_uuid_bytes("c32c7d56-a472-44bb-ac09-f8b526efa8c1")
U2 = R.layer_uuid_bytes("5cea2e10-36bc-4dd5-90dc-bfd61e13a1f9")
# The board's own list on 2026-09-10 (device/out/after-a3-outputs-test-20260910.json,
# layer_list_raw minus its leading count byte). Solid / breathe / swirl.
BOARD_LIST = bytes.fromhex(
    "000000100cb76a711d4243c88b4eab1c521695c9"
    "01010110c32c7d56a47244bbac09f8b526efa8c1"
    "020203105cea2e1036bc4dd590dcbfd61e13a1f9")


def state(anims=(0, 1, 3)):
    d = F.DesiredState()
    for i, u in enumerate((U0, U1, U2)):
        d.layers[i] = {0: (R.KEY_PRESS, R.encode_keypress("key", "A"))}
        d.layer_uuids[i] = u
        d.layer_animations[i] = anims[i]
    return d


def test_an_unchanged_flash_still_writes_the_full_list_and_nothing_else():
    d, cur = state(), state()
    ops = F.compute_plan(d, cur)
    assert [o.label for o in ops] == [F.LIGHTING_RESTORE_LABEL]
    assert ops[0].sub == R.WRITE_LAYER_LIST


def test_the_payload_is_the_boards_own_table_byte_for_byte():
    """Identical to what the board holds -- the encoder reproduces the captured list exactly,
    so the write changes nothing on disk and only resets the runtime effect."""
    ops = F.compute_plan(state(), state())
    assert ops[-1].payload == bytes([0]) + BOARD_LIST


def test_it_is_the_last_op_after_a_real_change():
    d, cur = state(), state()
    d.layers[1][5] = (R.KEY_PRESS, R.encode_keypress("key", "B"))
    d.leds[2] = {0: (120, 100)}
    labels = [o.label for o in F.compute_plan(d, cur)]
    assert labels[-1] == F.LIGHTING_RESTORE_LABEL
    assert labels[:-1] == ["layer 1", "led 2"]


def test_a_board_flashed_from_scratch_does_not_get_the_list_twice():
    """current=None makes _layer_list_ops write the whole table already; the same bytes are not
    sent again at the end."""
    ops = F.compute_plan(state(), None)
    lists = [o for o in ops if o.sub == R.WRITE_LAYER_LIST]
    assert len(lists) == 1
    assert lists[0].payload == bytes([0]) + BOARD_LIST


def test_a_partial_identity_table_still_writes_nothing():
    """The same rule as _layer_list_ops: naming some layers and not others is worse than silence."""
    d, cur = state(), state()
    del d.layer_uuids[2]
    assert F.compute_plan(d, cur) == []


def test_an_animation_change_is_written_once_in_the_diff_and_again_in_full():
    """Two list writes and both are right: the diff entry is NayaFlow's sparse form, the trailing
    full table is the restore. They differ, so neither is dropped."""
    d, cur = state((0, 1, 3)), state((0, 0, 3))
    ops = [o for o in F.compute_plan(d, cur) if o.sub == R.WRITE_LAYER_LIST]
    assert len(ops) == 2
    assert ops[0].label.startswith("layer list: 1") and ops[1].label == F.LIGHTING_RESTORE_LABEL


class _Resp:
    valid = True

    def __init__(self, payload):
        self.payload = payload


class FakeTransport:
    """Answers READ_LAYER_LIST with the board's table; records every other frame."""
    def __init__(self, port, dest):
        self.connected, self.frames = False, []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    @property
    def is_connected(self):
        return self.connected

    def _send_raw(self, frame, timeout):
        self.frames.append(bytes(frame))
        if frame[6:8] == R.READ_LAYER_LIST.to_bytes(2, "big"):
            return [_Resp(bytes([3]) + BOARD_LIST)]
        return []


def test_the_service_reads_the_list_and_writes_it_straight_back(monkeypatch):
    monkeypatch.setattr(S, "SerialTransport", FakeTransport)
    svc = S.DeviceService()

    class Dev:
        port, side = "COM9", "left"
    monkeypatch.setattr(svc, "_require_side", lambda side, serial=None: Dev())
    out = svc.restore_lighting("left")
    assert out["ok"] and out["layers"] == 3
    assert out["animations"] == {0: "solid", 1: "breathe", 2: "swirl"}
    t = svc._transports["COM9"]
    writes = [f for f in t.frames if f[6:8] == R.WRITE_LAYER_LIST.to_bytes(2, "big")]
    assert len(writes) == 1
    assert writes[0] == R.frames_for(0x50, R.WRITE_LAYER_LIST, bytes([0]) + BOARD_LIST)[0]
