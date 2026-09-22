"""Validate the WET flash loop (send -> ack-check -> read-back verify) with a mock transport.

No device: a fake transport records the frames and returns programmable acks, and a fake reader
returns a programmable read-back. Proves the loop's control flow — OK -> verified, bad ack ->
abort (stops, doesn't blind-continue), acks-ok-but-readback-differs -> verify-failed — so the
real Phase C run only swaps in a live transport + reader.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402


@dataclass
class FakeResp:
    valid: bool
    flags: int
    payload: bytes = b""


class MockTransport:
    """Records every frame and returns a preset ack per call (default OK)."""
    def __init__(self, acks=None):
        self.frames = []
        self._acks = list(acks) if acks else None

    def _send_raw(self, frame, timeout):
        self.frames.append(frame)
        flags = 0x00
        if self._acks is not None:
            flags = self._acks[len(self.frames) - 1] if len(self.frames) - 1 < len(self._acks) else 0x00
        return [FakeResp(valid=True, flags=flags, payload=b"\x00")]


def _desired_one_key(layer=3, pos=0x20, code="B") -> F.DesiredState:
    d = F.DesiredState()
    d.layers[layer] = {pos: (R.KEY_PRESS, R.encode_keypress("key", code))}
    return d


def test_wet_happy_path_verified() -> None:
    desired = _desired_one_key()
    tx = MockTransport()
    # reader returns exactly what we intended -> verified
    result = F.flash(desired, transport=tx, dry_run=False, full=True, reader=lambda: desired)
    assert result["status"] == "verified", result
    assert result["verify"] == []
    assert len(tx.frames) == result["frames"] > 0
    print(f"Wet happy path OK: {result['frames']} frames sent, all acked 0x00, read-back verified")


def test_wet_bad_ack_aborts() -> None:
    desired = _desired_one_key()
    tx = MockTransport(acks=[0xEA])   # first frame rejected
    result = F.flash(desired, transport=tx, dry_run=False, full=True, reader=lambda: desired)
    assert result["status"] == "aborted" and result["ack_flags"] == 0xEA
    assert len(tx.frames) == 1, "must stop at the first bad ack, not blind-continue"
    print("Wet abort OK: bad ack (0xEA) stops immediately, no further frames sent")


def test_wet_verify_failure_detected() -> None:
    desired = _desired_one_key(code="B")
    tx = MockTransport()                       # all acks OK
    wrong = _desired_one_key(code="C")         # device read-back shows a different key
    result = F.flash(desired, transport=tx, dry_run=False, full=True, reader=lambda: wrong)
    assert result["status"] == "verify-failed", result
    assert result["verify"] and result["verify"][0]["kind"] == "layer"
    print(f"Wet verify OK: acks passed but read-back differed -> verify-failed ({len(result['verify'])} mismatch)")


def test_diff_desired_ignores_readback_padding() -> None:
    """A full device read has positions we didn't set; diff only checks what we intended."""
    desired = _desired_one_key(layer=3, pos=0x20, code="B")
    readback = _desired_one_key(layer=3, pos=0x20, code="B")
    readback.layers[3][0x21] = (R.NONE_BEH, b"")   # extra padding position
    assert F.diff_desired(desired, readback) == []
    print("Diff OK: read-back padding ignored, only intended positions checked")


def test_a_position_absent_from_the_readback_counts_as_none() -> None:
    """SCRUM-112. A layer with no second-bank records reads back stopping at 0x51 -- the device
    does not return the bank -- while compute_plan adds the NONE shadows a profile owes for every
    key it sets. The write diff already treats absent as NONE and rightly skips such a layer; the
    verify must agree, or every good sync flash is reported as failed on the layers it left alone.
    Measured twice on 2026-09-21: layer 0 verified clean, layers 1 and 2 'failed' at 82+."""
    desired = _desired_one_key(layer=1, pos=0x20, code="B")
    desired.layers[1][0x20 + 0x52] = (R.NONE_BEH, b"")      # the shadow the profile owes
    readback = _desired_one_key(layer=1, pos=0x20, code="B")
    assert 0x20 + 0x52 not in readback.layers[1], "the read must model a bank the device omits"
    assert F.diff_desired(desired, readback) == []
    print("Diff OK: an owed NONE shadow the device does not return is not a mismatch")


def test_a_real_record_missing_from_the_readback_is_still_a_mismatch() -> None:
    """Patience is not credulity: a key the profile SETS that the board does not carry is a
    failed write and must still be reported, with got=null so the reader can tell absent
    from wrong."""
    desired = _desired_one_key(layer=1, pos=0x20, code="B")
    readback = F.DesiredState(layers={1: {}})
    mism = F.diff_desired(desired, readback)
    assert mism and mism[0]["pos"] == 0x20 and mism[0]["got"] is None


def test_a_none_the_board_did_not_honour_is_still_a_mismatch() -> None:
    """The other direction of the same rule: wanting NONE where the board holds a record."""
    desired = F.DesiredState(layers={1: {0x72: (R.NONE_BEH, b"")}})
    readback = _desired_one_key(layer=1, pos=0x72, code="B")
    assert [m["pos"] for m in F.diff_desired(desired, readback)] == [0x72]


if __name__ == "__main__":
    test_wet_happy_path_verified()
    test_wet_bad_ack_aborts()
    test_wet_verify_failure_detected()
    test_diff_desired_ignores_readback_padding()
