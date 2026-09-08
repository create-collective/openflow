"""Read the keymap off a connected Naya Create over USB CDC (REMAP protocol) and
translate it into OpenFlow's action vocabulary.

This is the in-app version of tools/naya_import_keymap.py: it powers the
"Read from keyboard" button. It reads every layer's binding records and the LED
map via the chunked flags=0x01 continue protocol (docs/remap-protocol-live.md),
then normalizes each binding to a NayaFlow/OpenFlow action_code — including the
shifted-symbol dictionary so a Shift+key chord becomes its real glyph (e.g.
Shift+0 -> RIGHT_PARENTHESIS) instead of an unrecognized "LSHIFT + NUMBER_0".

Read-only: no writes, no 0x10CA, no --force.
"""
from __future__ import annotations

import colorsys

from .._vendor.nayactl.constants import EOT, SOURCE_HOST
from .._vendor.nayactl.protocol import xor_checksum

# --------------------------------------------------------------------------- #
# HID usage -> action_code vocabulary                                         #
# --------------------------------------------------------------------------- #

PAGE7: dict[int, str] = {
    0x28: "RETURN", 0x29: "ESC", 0x2A: "BACKSPACE", 0x2B: "TAB", 0x2C: "SPACE",
    0x2D: "MINUS", 0x2E: "EQUAL", 0x2F: "LEFT_BRACKET", 0x30: "RIGHT_BRACKET",
    0x31: "BACKSLASH", 0x32: "NON_US_HASH", 0x33: "SEMICOLON", 0x34: "SINGLE_QUOTE",
    0x35: "GRAVE", 0x36: "COMMA", 0x37: "PERIOD", 0x38: "SLASH", 0x39: "CAPSLOCK",
    0x46: "PRINTSCREEN", 0x47: "SCROLLLOCK", 0x48: "PAUSE_BREAK",
    0x49: "INSERT", 0x4A: "HOME", 0x4B: "PG_UP", 0x4C: "DELETE", 0x4D: "END",
    0x4E: "PG_DN", 0x4F: "RIGHT", 0x50: "LEFT", 0x51: "DOWN", 0x52: "UP",
    0x53: "KP_NUMLOCK", 0x54: "KP_DIVIDE", 0x55: "KP_MULTIPLY", 0x56: "KP_MINUS",
    0x57: "KP_PLUS", 0x58: "KP_ENTER", 0x62: "KP_NUMBER_0", 0x63: "KP_DOT",
    0x64: "NON_US_BACKSLASH", 0x65: "K_APP",
}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    PAGE7[0x04 + _i] = _c
for _n in range(1, 10):
    PAGE7[0x1E + (_n - 1)] = f"NUMBER_{_n}"
PAGE7[0x27] = "NUMBER_0"
for _n in range(1, 13):
    PAGE7[0x3A + (_n - 1)] = f"F{_n}"
for _n in range(1, 13):
    PAGE7[0x68 + (_n - 1)] = f"F{_n + 12}"
for _n in range(1, 10):
    PAGE7[0x59 + (_n - 1)] = f"KP_NUMBER_{_n}"

MODIFIER_ID = {
    0xE0: "LCTRL", 0xE1: "LSHIFT", 0xE2: "LALT", 0xE3: "LGUI",
    0xE4: "RCTRL", 0xE5: "RSHIFT", 0xE6: "RALT", 0xE7: "RGUI",
}
MOD_BITS = ["LCTRL", "LSHIFT", "LALT", "LGUI", "RCTRL", "RSHIFT", "RALT", "RGUI"]
SHIFT_BITS = 0x02 | 0x20  # LShift or RShift

PAGE12: dict[int, str] = {
    0x30: "C_POWER", 0x6F: "C_BRIGHTNESS_INC", 0x70: "C_BRIGHTNESS_DEC",
    0xB0: "C_PLAY", 0xB1: "C_PAUSE", 0xB3: "C_FAST_FORWARD", 0xB4: "C_REWIND",
    0xB5: "C_NEXT", 0xB6: "C_PREVIOUS", 0xB7: "C_STOP", 0xCD: "C_PLAY_PAUSE",
    0xE2: "C_MUTE", 0xE9: "C_VOL_UP", 0xEA: "C_VOL_DOWN",
}

# The normalization dictionary: base action_code (US-QWERTY) + Shift -> its glyph.
# Fixes the "LSHIFT + NUMBER_0" display and NayaFlow "unknown" problem.
SHIFTED_SYMBOL: dict[str, str] = {
    "NUMBER_1": "EXCLAMATION", "NUMBER_2": "AT_SIGN", "NUMBER_3": "HASH",
    "NUMBER_4": "DOLLAR", "NUMBER_5": "PERCENT", "NUMBER_6": "CARET",
    "NUMBER_7": "AMPERSAND", "NUMBER_8": "ASTERISK", "NUMBER_9": "LEFT_PARENTHESIS",
    "NUMBER_0": "RIGHT_PARENTHESIS", "MINUS": "UNDERSCORE", "EQUAL": "PLUS",
    "LEFT_BRACKET": "LEFT_BRACE", "RIGHT_BRACKET": "RIGHT_BRACE", "BACKSLASH": "PIPE",
    "SEMICOLON": "COLON", "SINGLE_QUOTE": "DOUBLE_QUOTES", "COMMA": "LESS_THAN",
    "PERIOD": "GREATER_THAN", "SLASH": "QUESTION", "GRAVE": "TILDE",
}

# REMAP behavior-type bytes (docs/remap-protocol-live.md + round-trip findings).
KEY_PRESS, TWO_PARAM, LAYER_HOLD, NONE_BEH, OUTPUTS = 0x01, 0x00, 0x05, 0x07, 0x08
# 0x08 was called LAYER_SW and decoded as a layer switch. It is `outputs` (ZMK &out), and the
# mistake actively CORRUPTED keymaps: reading a stock board turned the Bluetooth-output key into
# "Force Layer 2" and the USB-C key into "Force Layer 1", and the next flash wrote those back as
# real to_layer records. A read-then-reflash round trip destroyed both keys.
#
# Three independent lines agree:
#   * NayaCore's behaviour-type table (docs/reference/nayacore-vocabulary.json) has index 8 =
#     "outputs", and already carried a warning that our name was probably wrong;
#   * the stock read of 2026-09-01 (device/run-20260901-013431/left-keymap-decoded.json) holds
#     exactly two type-0x08 records, layer 2, adjacent: idx 0x2f param 02000000, 0x30 param
#     01000000;
#   * NayaFlow's own database has BT_OUT at 0x2f and USB_DEVICE at 0x30 in that same profile.
OUTPUT_SELECTOR = {1: "USB_DEVICE", 2: "BT_OUT"}
RGB_SYS, TRANS = 0x09, 0x0E
LAYER_TO, LAYER_TOGGLE = 0x0C, 0x0D   # 0x0c=TO_LAYER (Force), 0x0d=TOGGLE (verified)
MODULE_TYPE, UNKNOWN_02 = 0x78, 0x02
# Hold-tap records: 0x10 (8-byte header, e.g. OneKey Tap+Hold) and 0x03 (5-byte
# header, e.g. home-row mods). Same body: header + hold(4) + pad(4) + tap(4) + pad(4),
# so the header length is len(param) - 16 either way.
HOLD_TAP_TYPES = (0x10, 0x03)

BT_PROFILE = {0: "BT_DEVICE_1", 1: "BT_DEVICE_2", 2: "BT_DEVICE_3", 3: "BT_DEVICE_4"}
MAX_POSITION = 96

# A key has TWO records, 0x52 apart. The primary bank (0x00-0x51) holds tap + hold; the
# secondary bank (position + 0x52) holds double-tap + tap-hold in the same two slots. Captured
# live 2026-09-03: NayaFlow wrote pos 0x49 (tap B / hold Z) and pos 0x9b (tap X / hold Y), and
# pressing that key produced b / zzz / x / yyy for tap / hold / double-tap / tap+hold.
#
# This is what "four behaviours per key" actually is -- not four slots in one record. Reads that
# stop at 0x51 silently drop every double-tap and tap+hold binding on the board.
SECOND_BANK = 0x52
SECOND_BANK_BEHAVIOR = {"press": "double_tap", "hold": "tap_hold"}


def split_position(pos: int) -> tuple[int, bool]:
    """Device position -> (key position, is_secondary_bank)."""
    return (pos - SECOND_BANK, True) if pos >= SECOND_BANK else (pos, False)


class Unmapped(str):
    """An action_code we couldn't resolve; still a string so it round-trips, but
    flagged (prefixed) so the UI/report can show it needs an encoding."""
    def __new__(cls, raw: str):
        return super().__new__(cls, f"RAW_{raw}")


def _mods_str(mods: int) -> str:
    return " + ".join(name for i, name in enumerate(MOD_BITS) if mods & (1 << i))


def decode_keypress(param: bytes) -> tuple[str, str]:
    """4-byte KEY_PRESS param [id_lo][id_hi][page][mods] -> (action_type, code)."""
    if len(param) < 3:
        return "key", Unmapped(f"kp?{param.hex()}")
    uid = param[0] | (param[1] << 8)
    page = param[2]
    mods = param[3] if len(param) > 3 else 0
    if page == 0x07:
        if uid in MODIFIER_ID and mods == 0:
            return "modifier", MODIFIER_ID[uid]
        base = PAGE7.get(uid)
        if base is None:
            return "key", Unmapped(f"p07:{uid:02x}m{mods:02x}")
        if mods == 0:
            return "key", base
        if mods in (0x02, 0x20) and base in SHIFTED_SYMBOL:   # Shift + key = glyph
            return "key", SHIFTED_SYMBOL[base]
        return "shortcut_alias", f"{_mods_str(mods)} + {base}"
    if page == 0x0C:
        code = PAGE12.get(uid)
        return "key", code if code else Unmapped(f"p0c:{uid:02x}")
    return "key", Unmapped(f"p{page:02x}:{uid:02x}m{mods:02x}")


def translate(typ: int, param: bytes, order_to_layer: dict[int, str]) -> list[tuple[str, str, str]]:
    """One REMAP record -> [(behavior, action_type, action_code), ...]. [] = no binding."""
    def layer_code(prefix: str) -> str:
        tgt = int.from_bytes(param[:4], "little") if len(param) >= 4 else -1
        return f"{prefix}{order_to_layer.get(tgt, tgt)}"

    if typ == KEY_PRESS:
        if len(param) < 3:
            return []
        at, code = decode_keypress(param)
        return [("press", at, code)]
    if typ in (TRANS, NONE_BEH):
        return []
    if typ in HOLD_TAP_TYPES and len(param) >= 16:
        h = len(param) - 16          # header length (8 for 0x10, 5 for 0x03)
        h_at, h_code = decode_keypress(param[h:h + 4])       # &mt HOLD ...
        t_at, t_code = decode_keypress(param[h + 8:h + 12])  # ... TAP
        return [("press", t_at, t_code), ("hold", h_at, h_code)]
    if typ == LAYER_HOLD:
        return [("press", "layer_polite_hold", layer_code("MO_LAYER_"))]
    if typ == OUTPUTS:
        sel = int.from_bytes(param[:4], "little") if len(param) >= 4 else None
        code = OUTPUT_SELECTOR.get(sel)
        # An unknown selector stays RAW rather than being rounded to one of the two we know.
        # Guessing here is what produced the bug this branch replaces.
        return [("press", "out", code)] if code else []
    if typ == LAYER_TO:
        return [("press", "layer_rude_toggle", layer_code("TO_LAYER_"))]
    if typ == LAYER_TOGGLE:
        return [("press", "layer_polite_toggle", layer_code("TOGGLE_LAYER_"))]
    if typ == TWO_PARAM:
        if len(param) >= 8:
            a = int.from_bytes(param[:4], "little")
            b = int.from_bytes(param[4:8], "little")
            if a == 3:
                return [("press", "bluetooth", BT_PROFILE.get(b, Unmapped(f"bt:{b}")))]
            return [("press", "bluetooth", Unmapped(f"2p:{a},{b}"))]
        return []
    if typ == RGB_SYS:
        return [("press", "LED", Unmapped(f"led:{param.hex()}"))]
    if typ in (MODULE_TYPE, UNKNOWN_02):
        return []
    if not param:
        return []
    return [("press", f"t{typ:#x}", Unmapped(param.hex()))]


# --------------------------------------------------------------------------- #
# Record + LED parsing                                                        #
# --------------------------------------------------------------------------- #

def parse_records(data: bytes) -> list[tuple[int, int, bytes]]:
    recs, i = [], 0
    while i + 3 <= len(data):
        idx, typ, ln = data[i], data[i + 1], data[i + 2]
        param = data[i + 3:i + 3 + ln]
        if len(param) < ln:
            break
        recs.append((idx, typ, param))
        i += 3 + ln
    return recs


def parse_led_map(data: bytes) -> list[tuple[int, int, int]]:
    return [(data[i], data[i + 1] | (data[i + 2] << 8), data[i + 3])
            for i in range(0, len(data) - 3, 4)]


def hsv_to_hex(hue_deg: int, value: int) -> str:
    r, g, b = colorsys.hsv_to_rgb((hue_deg % 360) / 360.0, 1.0, max(0, min(100, value)) / 100.0)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


# --------------------------------------------------------------------------- #
# Device read (chunked continue protocol)                                     #
# --------------------------------------------------------------------------- #

CHUNK_MAX = 242
CAT_REMAP = 0x30
READ_LAYER_LIST, READ_LAYER_DATA, READ_LED_MAP = 0x1001, 0x1003, 0x100D


def _build(dest: int, sub: int, payload: bytes = b"", flags: int = 0x00) -> bytes:
    dr = bytes([(sub >> 8) & 0xFF, sub & 0xFF, flags]) + payload
    return bytes([SOURCE_HOST, 0, dest, 0, CAT_REMAP, len(dr)]) + dr + bytes([xor_checksum(dr), EOT])


def read_keymap(transport, dest: int) -> dict:
    """Read every layer's binding records and LED map from a connected half.

    `transport` is an already-connected SerialTransport (handshake done).
    Returns {"layers": {idx: [records]}, "led": {idx: [(i,hue,val)]}}.
    """
    def send(sub, payload=b"", flags=0x00, timeout=2.0):
        return [r for r in transport._send_raw(_build(dest, sub, payload, flags), timeout) if r.valid]

    def read_full(sub, layer):
        parts, first = [], True
        while True:
            r = send(sub, bytes([layer]), flags=0x00 if first else 0x01)
            if not r:
                break
            resp = r[0]
            p = bytes(resp.payload)
            parts.append(p if first else p[1:])
            first = False
            if resp.flags != 0x01 or len(p) < CHUNK_MAX:
                break
        stitched = b"".join(parts)
        return stitched[1:] if stitched[:1] == bytes([layer]) else stitched

    r = send(READ_LAYER_LIST)
    llp = bytes(r[0].payload) if r else b""
    entries = llp[1:]
    # Each entry is [idx][id][flag][len=0x10][uuid16]. The UUID is the layer's IDENTITY and the
    # only stable handle the device carries -- there is no name field anywhere in the protocol.
    # Keeping it is what lets a re-read update the layer it already knows (preserving the user's
    # name) instead of creating a fresh one every time.
    layer_idxs, layer_uuids = [], {}
    for k in range(0, len(entries) - 19, 20):
        blk = entries[k:k + 20]
        layer_idxs.append(blk[0])
        h = blk[4:20].hex()
        layer_uuids[blk[0]] = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    layers, led = {}, {}
    for li in layer_idxs:
        layers[li] = parse_records(read_full(READ_LAYER_DATA, li))
        led[li] = parse_led_map(read_full(READ_LED_MAP, li))
    return {"layers": layers, "led": led, "layer_uuids": layer_uuids,
            "bays": {li: decode_bays(recs) for li, recs in layers.items()}}


READ_MODULE_CONFIG_LIST = 0x1009
READ_MODULE_CONFIG_DATA = 0x100B


# Layer positions 0x4A-0x51 are the module BAYS, not keys: 4 module types x 2 sides, in type
# order. The value is the module-config SLOT bound to that bay on that layer, with 0x78 meaning
# "inherit from the base layer" and 0 meaning "nothing here". The names match NayaFlow's own
# module_config_bindings.binding_location, which independently confirms the layout.
BAY_LOCATIONS = {
    0x4A: "touch:keyboard_left",  0x4B: "touch:keyboard_right",
    0x4C: "track:keyboard_left",  0x4D: "track:keyboard_right",
    0x4E: "tune:keyboard_left",   0x4F: "tune:keyboard_right",
    0x50: "float:keyboard_left",  0x51: "float:keyboard_right",
}
BAY_INHERIT = 0x78


def decode_bays(records) -> dict:
    """One layer's records -> {binding_location: slot|'transparent'|'disabled'}."""
    out = {}
    for pos, typ, _param in records:
        loc = BAY_LOCATIONS.get(pos)
        if loc is None:
            continue
        out[loc] = "transparent" if typ == BAY_INHERIT else ("disabled" if typ == 0 else typ)
    return out


def read_module_configs(transport, dest: int, slots: range = range(8)) -> dict:
    """Read the module config list + every non-empty slot from a connected half.

    The keymap read deliberately does not do this -- it asks only for layers and LEDs -- so
    module data never reached the app at all. Returns {"list": raw_list_payload,
    "slots": {slot: [(field, type, value), ...]}}. Read-only.
    """
    def send(sub, payload=b"", flags=0x00, timeout=2.0):
        return [r for r in transport._send_raw(_build(dest, sub, payload, flags), timeout) if r.valid]

    def read_full(sub, index):
        parts, first = [], True
        while True:
            r = send(sub, bytes([index]), flags=0x00 if first else 0x01)
            if not r:
                break
            resp = r[0]
            p = bytes(resp.payload)
            parts.append(p if first else p[1:])
            first = False
            if resp.flags != 0x01 or len(p) < CHUNK_MAX:
                break
        stitched = b"".join(parts)
        return stitched[1:] if stitched[:1] == bytes([index]) else stitched

    r = send(READ_MODULE_CONFIG_LIST, b"\x00")
    raw_list = bytes(r[0].payload) if r else b""
    out = {}
    for slot in slots:
        recs = [(f, t, v) for f, t, v in parse_records(read_full(READ_MODULE_CONFIG_DATA, slot))
                if not (t == 0 and not v)]
        if recs:
            out[slot] = recs
    return {"list": raw_list, "slots": out}


def decode_keymap(read: dict, order_to_layer: dict[int, str]) -> dict:
    """Raw read -> {order: {position_id: [(behavior, action_type, code), ...]}} plus
    {"_colors": {order: {pos: hex}}, "_warnings": [...], "_dropped": [...]}."""
    out: dict = {}
    colors: dict = {}
    warnings: list[str] = []
    dropped: list = []
    for order, recs in sorted(read["layers"].items()):
        pos: dict = {}
        for idx, typ, param in recs:
            slots = translate(typ, param, order_to_layer)
            if not slots:
                continue
            key, secondary = split_position(idx)
            if key > MAX_POSITION:
                dropped.append([order, idx, typ])
                continue
            if secondary:
                # Same record shape, different meaning: this bank's tap slot is the key's
                # double-tap and its hold slot is the key's tap+hold.
                slots = [(SECOND_BANK_BEHAVIOR.get(b, b), at, code) for b, at, code in slots]
            for _b, _at, code in slots:
                if isinstance(code, Unmapped):
                    warnings.append(f"layer {order} pos {idx}: undecoded ({code})")
            pos.setdefault(key, [])
            pos[key] = [s for s in pos[key] if s[0] not in {b for b, _, _ in slots}] + slots
        out[order] = pos
    for order, entries in sorted(read.get("led", {}).items()):
        colors[order] = {i: hsv_to_hex(h, v) for i, h, v in entries if i <= MAX_POSITION and v > 0}
    out["_colors"] = colors
    out["_warnings"] = warnings
    out["_dropped"] = dropped
    return out
