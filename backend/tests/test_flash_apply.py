"""The wet-write loop: which acks are OK, and that a bad one stops everything.

A chunked write acks each continuation frame with flags=0x01 and only the last with 0x00 --
confirmed in the captured flash, where every multi-frame layer and LED write does exactly
that. Accepting only 0x00 would abort partway through a full layer and leave the keymap half
written, which is worse than not flashing at all.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402


class Ack:
    valid = True
    def __init__(self, flags, payload=b"\x00"):
        self.flags, self.payload = flags, payload


class FakeTransport:
    """Replays a scripted ack per frame and records what was sent."""
    def __init__(self, flags_sequence):
        self.flags = list(flags_sequence)
        self.frames = []
    def _send_raw(self, frame, timeout):
        self.frames.append(frame)
        f = self.flags.pop(0) if self.flags else 0x00
        return [] if f is None else [Ack(f)]


def _plan():
    desired = F.DesiredState(layers={0: {p: (R.KEY_PRESS, R.encode_keypress("key", "A"))
                                         for p in range(0x00, 0x40)}})
    plan = F.compute_plan(desired, None, full=True)
    return desired, plan, F.render_frames(plan, 0x50)


def test_chunked_continuation_acks_are_accepted():
    desired, plan, rendered = _plan()
    nframes = sum(len(f) for _, f in rendered)
    assert nframes > 1, "this test needs a write big enough to chunk"
    # every frame but the last acks 0x01, exactly as the capture shows
    t = FakeTransport([0x01] * (nframes - 1) + [0x00])
    res = F._apply(plan, rendered, t, desired, reader=None)
    assert res["status"] != "aborted", f"continuation acks were rejected: {res}"
    assert len(t.frames) == nframes, "not every frame was sent"
    print(f"  {nframes} frames, {nframes - 1} continuation acks, all accepted")


def test_a_bad_ack_stops_immediately():
    desired, plan, rendered = _plan()
    nframes = sum(len(f) for _, f in rendered)
    t = FakeTransport([0x01, 0xEA] + [0x00] * nframes)     # 0xEA = invalid
    res = F._apply(plan, rendered, t, desired, reader=None)
    assert res["status"] == "aborted", "a 0xEA ack did not abort the write"
    assert len(t.frames) == 2, f"kept sending after a bad ack ({len(t.frames)} frames)"
    print("  0xEA aborts at the frame it occurs on, nothing further sent")


def test_a_missing_ack_stops_immediately():
    desired, plan, rendered = _plan()
    t = FakeTransport([None])
    res = F._apply(plan, rendered, t, desired, reader=None)
    assert res["status"] == "aborted" and len(t.frames) == 1
    print("  a missing ack aborts too")


def test_verify_failure_is_reported_not_swallowed():
    desired, plan, rendered = _plan()
    nframes = sum(len(f) for _, f in rendered)
    t = FakeTransport([0x00] * nframes)
    # the device reads back empty -> every record differs
    res = F._apply(plan, rendered, t, desired, reader=lambda: F.DesiredState())
    assert res["status"] == "verify-failed" and res["verify"], "a failed verify was reported as success"
    print(f"  read-back mismatch surfaces as verify-failed ({len(res['verify'])} differences)")


if __name__ == "__main__":
    for fn in (test_chunked_continuation_acks_are_accepted,
               test_a_bad_ack_stops_immediately,
               test_a_missing_ack_stops_immediately,
               test_verify_failure_is_reported_not_swallowed):
        print(fn.__name__)
        fn()
    print("\nOK")
