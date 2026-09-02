"""REMAP protocol (category 0x30) encoders — the inverse of keymap_read.py.

The WRITE wire format is fully reverse-engineered from three real NayaFlow flashes
(docs/write-protocol-spec.md, docs/write-implementation-plan.md). Every encoder here is
the exact inverse of a decoder in `keymap_read.py` and reuses its dictionaries so they
cannot drift. These functions are PURE (no I/O) and are validated offline against the
captured frames (tests/test_remap_encode.py, "Phase A"). Device I/O lives in flash.py.

Records are the read record format: `[position][type][len][param]`; a layer/led/module
payload is `[index] + concatenated records`; frames chunk at 242 bytes via the byte-3
countdown, re-prefixing the index byte on every continuation (frames_for).
"""

from __future__ import annotations

from dataclasses import dataclass

from .._vendor.nayactl.constants import CAT_REMAP, EOT, SOURCE_HOST
from .._vendor.nayactl.protocol import xor_checksum
from . import keymap_read as kr

# --- Opcodes (subcmd IDs within category 0x30) ---
READ_LAYER_LIST = 0x1001
WRITE_LAYER_LIST = 0x1002
READ_LAYER_DATA = 0x1003
WRITE_LAYER_DATA = 0x1004
READ_MACRO_LIST = 0x1005
WRITE_MACRO_LIST = 0x1006
READ_MACRO_DATA = 0x1007
WRITE_MACRO_DATA = 0x1008
READ_MODULE_CONFIG_LIST = 0x1009
WRITE_MODULE_CONFIG_LIST = 0x100A
READ_MODULE_CONFIG_DATA = 0x100B
WRITE_MODULE_CONFIG_DATA = 0x100C
READ_LED_MAP_DATA = 0x100D
WRITE_LED_MAP_DATA = 0x100E
CLEAR_ALL_DATA = 0x10CA

CHUNK_MAX = 242
FULL_LAYER_POSITIONS = 82   # positions 0x00..0x51: whole board (both halves) + 8 module slots
MODULE_POSITIONS = range(0x4A, 0x52)

# Behavior-type bytes (mirror keymap_read).
KEY_PRESS = kr.KEY_PRESS         # 0x01
TWO_PARAM = kr.TWO_PARAM         # 0x00
LAYER_HOLD = kr.LAYER_HOLD       # 0x05  (MO)
NONE_BEH = kr.NONE_BEH           # 0x07
LAYER_SW = kr.LAYER_SW           # 0x08
LAYER_TO = kr.LAYER_TO           # 0x0c  (TO / rude toggle)
LAYER_TOGGLE = kr.LAYER_TOGGLE   # 0x0d  (polite toggle)
TRANS = kr.TRANS                 # 0x0e
MODULE_TYPE = kr.MODULE_TYPE     # 0x78
HOLD_TAP_HOME = 0x03             # 5-byte header (home-row mods)
HOLD_TAP_ONEKEY = 0x10           # 8-byte header (one-key tap+hold)

# --- reverse dictionaries (built once from keymap_read's forward tables) ---
PAGE7_REV = {v: k for k, v in kr.PAGE7.items()}
PAGE12_REV = {v: k for k, v in kr.PAGE12.items()}
MODIFIER_REV = {v: k for k, v in kr.MODIFIER_ID.items()}
SHIFTED_REV = {v: k for k, v in kr.SHIFTED_SYMBOL.items()}
MOD_BIT = {name: 1 << i for i, name in enumerate(kr.MOD_BITS)}
BT_PROFILE_REV = {v: k for k, v in kr.BT_PROFILE.items()}
# NayaFlow token spellings that differ from our canonical codes (verified from captures).
CODE_ALIASES = {"ENTER": "RETURN"}


@dataclass
class LayerBinding:
    """One key binding within a layer (maps to the key_bindings table)."""

    position_id: int
    behavior: str
    action_type: str
    action_code: str
    context: str | None = None


class RemapEncodeError(ValueError):
    """A binding/action we do not know how to encode to device bytes."""


# --------------------------------------------------------------------------- #
# keypress: [id_lo][id_hi][page][mods]  (inverse of decode_keypress)          #
# --------------------------------------------------------------------------- #

def encode_keypress(action_type: str, action_code: str) -> bytes:
    """(action_type, action_code) -> 4-byte KEY_PRESS param."""
    code = CODE_ALIASES.get(action_code, action_code)

    if action_type == "modifier":
        if code not in MODIFIER_REV:
            raise RemapEncodeError(f"unknown modifier {action_code!r}")
        return bytes([MODIFIER_REV[code], 0x00, 0x07, 0x00])

    if action_type == "shortcut_alias":
        *mod_toks, base = [t.strip() for t in code.split(" + ")]
        mods = 0
        for t in mod_toks:
            t = t.strip("[]")                      # a bracketed modifier still sets its bit
            if t not in MOD_BIT:
                raise RemapEncodeError(f"unknown modifier token {t!r} in {action_code!r}")
            mods |= MOD_BIT[t]
        base = CODE_ALIASES.get(base, base)
        if base in PAGE7_REV:
            return bytes([PAGE7_REV[base], 0x00, 0x07, mods])
        if base in PAGE12_REV:
            return bytes([PAGE12_REV[base], 0x00, 0x0C, mods])
        raise RemapEncodeError(f"unknown base key {base!r} in {action_code!r}")

    # plain key
    if code in PAGE7_REV:
        return bytes([PAGE7_REV[code], 0x00, 0x07, 0x00])
    if code in SHIFTED_REV:                        # a shifted glyph = base + LShift
        return bytes([PAGE7_REV[SHIFTED_REV[code]], 0x00, 0x07, 0x02])
    if code in PAGE12_REV:
        return bytes([PAGE12_REV[code], 0x00, 0x0C, 0x00])
    raise RemapEncodeError(f"unknown key {action_code!r}")


# --------------------------------------------------------------------------- #
# param builders per behavior type                                            #
# --------------------------------------------------------------------------- #

def _holdtap_body(flavour: int, term: int, hold_kp: bytes, tap_kp: bytes) -> bytes:
    """The shared 21-byte hold-tap body: 01 01 <flavour> <term u16 LE> hold(4) pad(4) tap(4) pad(4)."""
    if len(hold_kp) != 4 or len(tap_kp) != 4:
        raise RemapEncodeError("hold/tap keypress must be 4 bytes")
    return (bytes([0x01, 0x01, flavour & 0xFF]) + (term & 0xFFFF).to_bytes(2, "little")
            + hold_kp + b"\x00\x00\x00\x00" + tap_kp + b"\x00\x00\x00\x00")


def encode_holdtap_param(kind: int, flavour: int, term: int, hold_kp: bytes, tap_kp: bytes) -> bytes:
    """0x03 = the 21-byte body; 0x10 = <term u16 LE> 03 <body> (term repeated), 24 bytes."""
    body = _holdtap_body(flavour, term, hold_kp, tap_kp)
    if kind == HOLD_TAP_HOME:
        return body
    if kind == HOLD_TAP_ONEKEY:
        return (term & 0xFFFF).to_bytes(2, "little") + bytes([0x03]) + body
    raise RemapEncodeError(f"not a hold-tap type: {kind:#x}")


def encode_layer_param(target: int) -> bytes:
    """MO/TO/TOGGLE/layer-switch param = target layer index, u32 LE."""
    return (target & 0xFFFFFFFF).to_bytes(4, "little")


def encode_twoparam(a: int, b: int) -> bytes:
    """0x00 two-param body = two u32 LE (e.g. bluetooth (3, profile))."""
    return (a & 0xFFFFFFFF).to_bytes(4, "little") + (b & 0xFFFFFFFF).to_bytes(4, "little")


# --------------------------------------------------------------------------- #
# record / payload assembly                                                   #
# --------------------------------------------------------------------------- #

def record(position: int, type_byte: int, param: bytes = b"") -> bytes:
    """[position][type][len][param]."""
    if not 0 <= position <= 0xFF or len(param) > 0xFF:
        raise RemapEncodeError(f"record out of range pos={position} len={len(param)}")
    return bytes([position, type_byte, len(param)]) + param


def encode_layer_data(layer: int, records: list[bytes]) -> bytes:
    """[layer] + concatenated binding records. Sparse (edit) or full (new layer)."""
    return bytes([layer]) + b"".join(records)


def encode_led_record(led: int, hue_deg: int, value: int) -> bytes:
    """[led][hue u16 LE][value]."""
    return bytes([led & 0xFF]) + (hue_deg & 0xFFFF).to_bytes(2, "little") + bytes([value & 0xFF])


def encode_led_map(layer: int, led_records: list[bytes]) -> bytes:
    return bytes([layer]) + b"".join(led_records)


def encode_module_field(field: int, value: bytes, type_byte: int = 0x01) -> bytes:
    """[field][type][len][value]. u8 fields (speed/scroll/accel) len 1; keypress fields len 4."""
    return bytes([field, type_byte, len(value)]) + value


def encode_module_config(slot: int, field_records: list[bytes]) -> bytes:
    return bytes([slot]) + b"".join(field_records)


def encode_layer_list(entries: list[tuple[int, int, bytes]]) -> bytes:
    """[00] + per-layer [idx][id][00][10][uuid16] (add) or [idx] 00 00 00 (delete, id=0/len=0).

    entries: (idx, list_id, uuid16_or_empty). An empty uuid encodes a deletion.
    """
    out = bytearray([0x00])
    for idx, list_id, uuid in entries:
        if uuid:
            if len(uuid) != 16:
                raise RemapEncodeError("layer-list uuid must be 16 bytes")
            out += bytes([idx, list_id, 0x00, 0x10]) + uuid
        else:
            out += bytes([idx, 0x00, 0x00, 0x00])
    return bytes(out)


def encode_timeouts(idle_ms: int, sleep_ms: int, sleep_batt_ms: int) -> bytes:
    """SYSTEM 0xFE/0x100A payload: three u32 LE milliseconds."""
    return b"".join((v & 0xFFFFFFFF).to_bytes(4, "little") for v in (idle_ms, sleep_ms, sleep_batt_ms))


# --------------------------------------------------------------------------- #
# framing + chunking (inverse of keymap_read.read_full's continue loop)       #
# --------------------------------------------------------------------------- #

def _frame(dest: int, cat: int, sub: int, byte3: int, payload: bytes, flags: int = 0x00) -> bytes:
    dr = bytes([(sub >> 8) & 0xFF, sub & 0xFF, flags]) + payload
    return (bytes([SOURCE_HOST, 0, dest, byte3 & 0xFF, cat, len(dr)]) + dr
            + bytes([xor_checksum(dr), EOT]))


def frames_for(dest: int, sub: int, payload: bytes, *, cat: int = CAT_REMAP) -> list[bytes]:
    """Split a payload into CDC frames.

    <=242 bytes -> one frame, byte3=0. Larger -> chunks of <=242 with a byte-3 countdown
    (N-1 .. 0); every continuation re-prefixes payload[0] (the layer/index byte), exactly
    as the device echoes it on read. `flags` stays 0x00 on writes.
    """
    if len(payload) <= CHUNK_MAX:
        return [_frame(dest, cat, sub, 0x00, payload)]
    prefix = payload[:1]                       # the layer/index byte, repeated on each continuation
    chunks = [payload[:CHUNK_MAX]]
    rest = payload[CHUNK_MAX:]
    step = CHUNK_MAX - 1                        # continuations carry the prefix byte + (242-1) data
    for i in range(0, len(rest), step):
        chunks.append(prefix + rest[i:i + step])
    n = len(chunks)
    return [_frame(dest, cat, sub, n - 1 - i, ch) for i, ch in enumerate(chunks)]
