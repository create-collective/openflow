"""Dry-run flash test: recreate a full flash of a real keymap 100% offline and validate it.

Takes a real device read (device/out/decode-current.json), builds the desired state, runs
flash.flash(dry_run=True) to render the full WRITE sequence, then parses those frames back
(as the device would receive them) and asserts they reconstruct the same keymap. No hardware,
nothing sent. Run standalone or under pytest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
# Walk up to whichever directory holds the shared device captures. NayaOS nests this tree
# under openflow/ while this repository has it at the root, so a hardcoded parent index
# only works in one of them.
_REPO = next(p for p in _BACKEND.parents if (p / "device").is_dir())
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import flash as F  # noqa: E402
from openflow_backend.device import keymap_read as kr  # noqa: E402

READ_JSON = _REPO / "device" / "out" / "decode-current.json"

SOT, EOT = 0xAA, 0x04


def _parse_frames(stream: bytes) -> list[dict]:
    """Reassemble CDC frames from a raw OUT byte stream (mirror of the analyzer)."""
    frames, i, n = [], 0, len(stream)
    while i < n:
        if stream[i] != SOT:
            i += 1
            continue
        if i + 6 > n:
            break
        dest, byte3, cat, size = stream[i + 2], stream[i + 3], stream[i + 4], stream[i + 5]
        end = i + 6 + size
        if end + 1 >= n or stream[end + 1] != EOT:
            i += 1
            continue
        dr = stream[i + 6:end]
        frames.append({"dest": dest, "byte3": byte3, "cat": cat,
                       "sub": (dr[0] << 8) | dr[1], "flags": dr[2], "payload": bytes(dr[3:])})
        i = end + 2
    return frames


def _stitch(frames: list[dict]) -> bytes:
    """Reverse frames_for: byte-3 countdown groups, continuations drop the re-echoed index byte."""
    out = frames[0]["payload"]
    for f in frames[1:]:
        out += f["payload"][1:]
    return out


def test_full_flash_roundtrip() -> None:
    read = json.loads(READ_JSON.read_text())
    desired = F.desired_from_read(read)

    result = F.flash(desired, dry_run=True, full=True)
    assert result["dry_run"] is True
    frames = [bytes.fromhex(h) for h in result["frames"]]
    assert frames, "no frames rendered"

    # (1) framing round-trip: re-parse the rendered stream, regroup by op, stitch, compare to
    #     each op's payload. Also asserts every frame is well-formed and XOR/EOT-correct.
    plan = F.compute_plan(desired, full=True)
    idx = 0
    parsed_layers: dict[int, dict[int, tuple[int, bytes]]] = {}
    parsed_leds: dict[int, dict[int, tuple[int, int]]] = {}
    for op in plan:
        n = len(F.R.frames_for(0x50, op.sub, op.payload, cat=op.cat))
        grp = _parse_frames(b"".join(frames[idx:idx + n]))
        assert len(grp) == n, f"frame regroup mismatch for {op.label}"
        assert _stitch(grp) == op.payload, f"stitched payload != op payload for {op.label}"
        idx += n
        # (2) content: parse each write back into records/leds
        # update, not assign: one layer arrives as several writes when it is too big for
        # two CDC frames (SCRUM-100), and each part carries a slice of the same layer.
        if op.sub == F.R.WRITE_LAYER_DATA:
            li = op.payload[0]
            parsed_layers.setdefault(li, {}).update(
                {p: (t, prm) for p, t, prm in kr.parse_records(op.payload[1:])})
        elif op.sub == F.R.WRITE_LED_MAP_DATA:
            li = op.payload[0]
            parsed_leds.setdefault(li, {}).update(
                {i: (h, v) for i, h, v in kr.parse_led_map(op.payload[1:])})
    assert idx == len(frames), "leftover frames not accounted for"

    # every desired binding survives the round-trip, byte-identical
    checked = 0
    for li, poss in desired.layers.items():
        assert li in parsed_layers, f"layer {li} missing from flash output"
        for pos, (typ, param) in poss.items():
            assert parsed_layers[li].get(pos) == (typ, param), (
                f"layer {li} pos {pos}: {parsed_layers[li].get(pos)} != {(typ, param.hex())}")
            checked += 1
    for li, leds in desired.leds.items():
        for i, (h, v) in leds.items():
            assert parsed_leds.get(li, {}).get(i) == (h, v), f"led {li}:{i} mismatch"

    s = result["summary"]
    print(f"Dry flash OK: {len(plan)} ops, {s['total_frames']} frames, {s['total_bytes']} payload bytes; "
          f"{checked} bindings round-tripped across layers {sorted(desired.layers)}")


def test_diff_plan_is_sparse() -> None:
    """A one-key change against a current state emits exactly one layer write, and no LED/timeout."""
    read = json.loads(READ_JSON.read_text())
    current = F.desired_from_read(read)
    desired = F.desired_from_read(read)
    li = sorted(desired.layers)[0]
    some_pos = sorted(desired.layers[li])[0]
    desired.layers[li][some_pos] = (F.R.KEY_PRESS, F.R.encode_keypress("key", "Z"))

    plan = F.compute_plan(desired, current)
    labels = [op.label for op in plan]
    # The trailing layer-list write is not a diff: every flash ends with it so the board's
    # lighting comes back (measured 2026-09-10, test_lighting_restore.py) -- but only with a
    # complete identity table, and this fixture is a read from before uuids were captured, so
    # it carries none. Either way, everything before it must be exactly the one changed layer.
    tail = [F.LIGHTING_RESTORE_LABEL] if desired.layer_uuids else []
    # A layer is written in parts when it exceeds two CDC frames (SCRUM-100). The point of
    # this test is WHICH layer is written and that nothing else is, so the part suffix is
    # dropped and repeats collapsed -- several parts of one layer are still one layer.
    base = [lbl.split(" (part ")[0] for lbl in labels]
    deduped = [lbl for n, lbl in enumerate(base) if n == 0 or lbl != base[n - 1]]
    assert deduped == [f"layer {li}"] + tail, f"expected only the changed layer, got {labels}"
    print(f"Diff plan OK: one-key change -> {labels}")


if __name__ == "__main__":
    test_full_flash_roundtrip()
    test_diff_plan_is_sparse()
