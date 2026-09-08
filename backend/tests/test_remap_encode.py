"""Phase A: validate the REMAP encoders against real captured NayaFlow flashes.

For every WRITE frame NayaCore actually sent (fixture extracted from
device/out/flash{,2,3}.pcap), this:
  1. re-chunks the logical payload with frames_for() and asserts the frames come out
     byte-identical to what was captured (framer/chunker);
  2. decodes each binding/LED/module/layer-list record with keymap_read and re-encodes
     it with remap.py, asserting byte-identical (the encoders).
No hardware. Run standalone (`python tests/test_remap_encode.py`) or under pytest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import keymap_read as kr  # noqa: E402
from openflow_backend.device import remap as R  # noqa: E402

FIXTURE = json.loads((Path(__file__).with_name("write-frames-fixture.json")).read_text())

LAYER_BEHAVIORS = {R.LAYER_HOLD, R.LAYER_TO, R.LAYER_TOGGLE}
# 0x08 used to be in the set above, named LAYER_SW. It is `outputs`, and the round trip passed
# anyway because an output selector and a layer index are BOTH u32 LE -- identical bytes, wrong
# meaning. That is exactly how the wrong name survived a byte-level test, so it gets its own
# case here rather than being folded back in with the layer behaviours.
OUTPUT_BEHAVIORS = {R.OUTPUTS}
EMPTY_BEHAVIORS = {R.NONE_BEH, R.TRANS, R.MODULE_TYPE}


# --------------------------------------------------------------------------- #
# per-record re-encoders (raw record bytes -> semantically re-encoded param)  #
# --------------------------------------------------------------------------- #

def _reencode_binding(typ: int, param: bytes) -> tuple[bytes, bool]:
    """Return (param', tested). tested=False means passthrough (no semantic transform)."""
    if typ == R.KEY_PRESS:
        at, code = kr.decode_keypress(param)
        if isinstance(code, kr.Unmapped):
            return param, False
        return R.encode_keypress(at, code), True
    if typ in (R.HOLD_TAP_HOME, R.HOLD_TAP_ONEKEY):
        body = param if typ == R.HOLD_TAP_HOME else param[3:]
        flavour, term = body[2], body[3] | (body[4] << 8)
        hold, tap = body[5:9], body[13:17]
        return R.encode_holdtap_param(typ, flavour, term, hold, tap), True
    if typ in OUTPUT_BEHAVIORS:
        assert len(param) == 4, f"output selector not 4 bytes: {param.hex()}"
        sel = int.from_bytes(param, "little")
        assert sel in (1, 2), f"unknown output selector {sel} (1=USB, 2=wireless)"
        return param, True
    if typ in LAYER_BEHAVIORS:
        assert len(param) == 4, f"layer param not 4 bytes: {param.hex()}"
        return R.encode_layer_param(int.from_bytes(param, "little")), True
    if typ == R.TWO_PARAM:
        if len(param) == 0:                              # blanked position in a cleared layer
            return b"", True
        assert len(param) == 8, f"two-param not 8 bytes: {param.hex()}"
        a = int.from_bytes(param[:4], "little")
        b = int.from_bytes(param[4:8], "little")
        return R.encode_twoparam(a, b), True
    if typ in EMPTY_BEHAVIORS:
        assert param == b"", f"expected empty param for {typ:#x}: {param.hex()}"
        return b"", True
    return param, False  # RGB (0x09) etc. — no encoder yet, passthrough


def _reencode_module_field(typ: int, value: bytes) -> tuple[bytes, bool]:
    if typ == R.KEY_PRESS and len(value) == 4:            # 1-finger tap = a keypress
        at, code = kr.decode_keypress(value)
        if not isinstance(code, kr.Unmapped):
            return R.encode_keypress(at, code), True
    return value, False                                    # u8 settings / none / axis fields


# --------------------------------------------------------------------------- #
# the checks                                                                  #
# --------------------------------------------------------------------------- #

def _check_write(w: dict, stats: dict) -> None:
    dest, sub, payload = w["dest"], w["sub"], bytes.fromhex(w["payload"])
    captured_frames = [bytes.fromhex(f) for f in w["frames"]]

    # (1) framer/chunker round-trip
    assert R.frames_for(dest, sub, payload) == captured_frames, (
        f"frames mismatch for sub={sub:#x} ({len(captured_frames)} chunks)")
    stats["frames"] += 1

    # (2) record round-trip
    if sub in (R.WRITE_LAYER_DATA, R.WRITE_MODULE_CONFIG_DATA):
        index, body = payload[:1], payload[1:]
        recs = kr.parse_records(body)
        assert sum(3 + len(p) for _, _, p in recs) == len(body), "record parse did not consume payload"
        rebuilt = bytearray()
        for idx, typ, param in recs:
            if sub == R.WRITE_LAYER_DATA:
                param2, tested = _reencode_binding(typ, param)
            else:
                param2, tested = _reencode_module_field(typ, param)
            if tested:
                assert param2 == param, (
                    f"sub={sub:#x} pos={idx} type={typ:#x}: {param2.hex()} != {param.hex()}")
                stats["records"] += 1
            else:
                stats["skipped"] += 1
            rebuilt += R.record(idx, typ, param2)
        assert index + bytes(rebuilt) == payload, "reassembled layer/module payload != captured"

    elif sub == R.WRITE_LED_MAP_DATA:
        index, body = payload[:1], payload[1:]
        leds = kr.parse_led_map(body)
        rebuilt = b"".join(R.encode_led_record(i, hue, val) for i, hue, val in leds)
        assert index + rebuilt == payload, "reassembled LED map != captured"
        stats["records"] += len(leds)

    elif sub == R.WRITE_LAYER_LIST:
        assert payload[0] == 0x00
        entries, i = [], 1
        while i + 4 <= len(payload):
            idx, list_id, ln = payload[i], payload[i + 1], payload[i + 3]  # payload[i+2] is 0x00
            uuid = payload[i + 4:i + 4 + ln]
            entries.append((idx, list_id, uuid))
            i += 4 + ln
        assert i == len(payload), "layer-list parse did not consume payload"
        assert R.encode_layer_list(entries) == payload, "re-encoded layer list != captured"
        stats["records"] += len(entries)


def _check_timeout(t: dict, stats: dict) -> None:
    payload = bytes.fromhex(t["payload"])
    idle, sleep, batt = (int.from_bytes(payload[k:k + 4], "little") for k in (0, 4, 8))
    assert R.encode_timeouts(idle, sleep, batt) == payload, "re-encoded timeouts != captured"
    stats["records"] += 1


def test_phase_a_roundtrip() -> None:
    stats = {"frames": 0, "records": 0, "skipped": 0}
    n_writes = n_timeouts = 0
    for cap in FIXTURE["captures"].values():
        for w in cap["remap_writes"]:
            _check_write(w, stats)
            n_writes += 1
        for t in cap["timeouts"]:
            _check_timeout(t, stats)
            n_timeouts += 1
    assert n_writes >= 15 and n_timeouts >= 1, "fixture looks empty"
    print(f"Phase A OK: {n_writes} writes / {n_timeouts} timeouts | "
          f"{stats['frames']} framer round-trips, {stats['records']} record round-trips, "
          f"{stats['skipped']} passthrough (RGB/u8/axis)")


if __name__ == "__main__":
    test_phase_a_roundtrip()
