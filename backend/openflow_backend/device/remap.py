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
OUTPUTS = kr.OUTPUTS             # 0x08  (&out; NOT a layer switch — see keymap_read)
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
# The outputs record (0x08, ZMK &out): param is the selector as u32 LE, 1 = USB, 2 = wireless.
# The mapping is NayaFlow's own -- its database holds BT_OUT at 0x2f and USB_DEVICE at 0x30 on
# the stock System layer, and the board reads 02000000 / 01000000 at exactly those positions --
# and NayaFlow has been captured writing these bytes to this board (four of them on layer 2,
# 2026-09-08). Writing them back is byte-identical to the vendor.
OUTPUT_SELECTOR_REV = {v: k for k, v in kr.OUTPUT_SELECTOR.items()}
BT_SELECT, BT_CLEAR_CMD = kr.BT_SELECT, kr.BT_CLEAR_CMD
STICKY_LAYER = kr.STICKY_LAYER   # 0x0b -- real, confirmed on hardware 2026-09-08
NAYA_SYSTEM = kr.NAYA_SYSTEM     # 0x06 -- Naya's own system actions
NAYA_COMMANDS_REV = {v: k for k, v in kr.NAYA_COMMANDS.items()}
# NayaFlow token spellings that differ from our canonical codes. ENTER is verified from captures;
# the rest are what NayaFlow's key RECORDER emits (renderer map, 2026-09-09 palette scrape) and
# what our own recorder (frontend recordkeys.js) emits for the same keys -- a binding recorded
# from a keypress carries these, and the encoder used to refuse every one of them.
CODE_ALIASES = {"ENTER": "RETURN", "ESCAPE": "ESC", "CAPS_LOCK": "CAPSLOCK",
                "SCROLL_LOCK": "SCROLLLOCK", "PAGE_UP": "PG_UP", "PAGE_DOWN": "PG_DN"}
# Modifier spellings a chord may carry. NayaFlow's chord class accepts LSHFT/RSHFT beside
# LSHIFT/RSHIFT, its own VS Code preset "LGUI + CTRL + F" uses a bare CTRL, and NayaCore.exe
# carries an 18-name alias table of its own (0x77bce8, docs/reference/nayacore-action-
# vocabulary.json) -- every spelling the vendor's serialiser accepts is accepted here.
MOD_TOKEN_ALIASES = {
    "CTRL": "LCTRL", "LEFT_CTRL": "LCTRL", "RIGHT_CTRL": "RCTRL",
    "SHIFT": "LSHIFT", "LEFT_SHIFT": "LSHIFT", "RIGHT_SHIFT": "RSHIFT", "LSHFT": "LSHIFT", "RSHFT": "RSHIFT",
    "ALT": "LALT", "LEFT_ALT": "LALT",
    "GUI": "LGUI", "META": "LGUI", "CMD": "LGUI", "WIN": "LGUI", "LEFT_GUI": "LGUI", "LEFT_META": "LGUI",
    "LMETA": "LGUI", "LCMD": "LGUI", "LWIN": "LGUI", "LEFT_WIN": "LGUI", "LEFT_COMMAND": "LGUI",
}
# NayaFlow's recorder stores a recorded chord with actionType "combo"; it is a shortcut_alias in
# every other respect, and is written as one.
CHORD_ACTION_TYPES = ("shortcut_alias", "combo")


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

# Shortcut bases that are not keyboard usages: the record holds the modifier and the user
# supplies the rest with the mouse.
MODIFIER_ONLY_BASES = {"CLICK", "MOUSE_CLICK", "LEFT_CLICK"}


def encode_keypress(action_type: str, action_code: str) -> bytes:
    """(action_type, action_code) -> 4-byte KEY_PRESS param."""
    code = CODE_ALIASES.get(action_code, action_code)

    if action_type == "modifier":
        code = MOD_TOKEN_ALIASES.get(code, code)
        if code not in MODIFIER_REV:
            raise RemapEncodeError(f"unknown modifier {action_code!r}")
        return bytes([MODIFIER_REV[code], 0x00, 0x07, 0x00])

    if action_type in CHORD_ACTION_TYPES:
        *mod_toks, base = [t.strip() for t in code.split(" + ")]
        mods = 0
        for t in mod_toks:
            # A BRACKETED modifier does not set its bit. It marks a modifier the context already
            # holds -- an app switcher keeping Alt down, say -- so the record carries only the
            # rest. Checked against a real flash capture: "[LALT] + TAB" was stored 2b000700 and
            # "[LALT] + LSHIFT + TAB" 2b000702, both without the LALT bit.
            if t.startswith("[") and t.endswith("]"):
                if MOD_TOKEN_ALIASES.get(t.strip("[]"), t.strip("[]")) not in MOD_BIT:
                    raise RemapEncodeError(f"unknown modifier token {t!r} in {action_code!r}")
                continue
            t = MOD_TOKEN_ALIASES.get(t, t)
            if t not in MOD_BIT:
                raise RemapEncodeError(f"unknown modifier token {t!r} in {action_code!r}")
            mods |= MOD_BIT[t]
        base = CODE_ALIASES.get(base, base)
        base = MOD_TOKEN_ALIASES.get(base, base)
        if base in MOD_BIT:
            # A bare modifier list ("LCTRL + LSHIFT"), which NayaFlow's chord grammar allows: the
            # last token is a modifier too, so there is no key. Stored the way the board stores
            # any modifiers-only chord -- usage 0, page 0, the bits -- the same form captured
            # for "[LALT] + CLICK" (00000004).
            return bytes([0x00, 0x00, 0x00, mods | MOD_BIT[base]])
        if base in PAGE7_REV:
            return bytes([PAGE7_REV[base], 0x00, 0x07, mods])
        if base in PAGE12_REV:
            return bytes([PAGE12_REV[base], 0x00, 0x0C, mods])
        # A base that is not a keyboard usage at all -- "LALT + CLICK" is "hold Alt, then click
        # with the mouse". The device stores the modifier alone, page 0: captured 00000004.
        if base in MODIFIER_ONLY_BASES:
            return bytes([0x00, 0x00, 0x00, mods])
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


# --- hold-tap (two actions on one key) -------------------------------------- #
# The header is NOT a constant: encode_holdtap_param builds it as 01 01 <flavour> <term u16 LE>
# (with the 0x10 OneKey form prefixing <term u16> 03). Two captures confirm both fields vary --
# `...0102c200` is flavour 2 / term 194 and `...0100c800` is flavour 0 / term 200.
#
# The flavour is the ZMK hold-tap enum and its valid range is 0-3 (hold-preferred, balanced,
# tap-preferred, tap-unless-interrupted; see _read_term_flavour in flash.py). Writing 4 there was
# accepted and stored and then stopped every key on the board until it was power-cycled, so this
# field must never be swept.
HOLD_TAP_FLAVOURS = range(0, 4)
DEFAULT_TAPPING_TERM = 200


def encode_hold_tap(tap: tuple[str, str], hold: tuple[str, str],
                    type_byte: int = HOLD_TAP_ONEKEY, flavour: int = 0,
                    term: int = DEFAULT_TAPPING_TERM) -> bytes:
    """(tap, hold) as (action_type, action_code) pairs -> a hold-tap binding param.

    Convenience wrapper over encode_holdtap_param for callers that have actions rather than
    encoded keypresses. Confirmed against the firmware: a key really does hold two different
    actions (captured with two ordinary keys, tap DELETE / hold BACKSPACE).
    """
    if flavour not in HOLD_TAP_FLAVOURS:
        raise RemapEncodeError(
            f"hold-tap flavour {flavour} is out of range {HOLD_TAP_FLAVOURS.start}-"
            f"{HOLD_TAP_FLAVOURS.stop - 1}; an invalid flavour stops the keyboard until it is "
            "power-cycled")
    return encode_holdtap_param(type_byte, flavour, term,
                                encode_keypress(*hold), encode_keypress(*tap))


def encode_layer_data(layer: int, records: list[bytes]) -> bytes:
    """[layer] + concatenated binding records. Sparse (edit) or full (new layer)."""
    return bytes([layer]) + b"".join(records)


# --- WRITE_LAYER_LIST ------------------------------------------------------------------------- #
# The layer list is the device's IDENTITY table: which UUID sits at which index. It is what a
# read matches app layers against, and OpenFlow never wrote it -- so a board flashed by us kept
# whatever identities NayaFlow last wrote while we rewrote the records underneath. Reading back
# then attributed everyone's bindings to the wrong layers.
#
# Both forms below are copied from captured NayaCore flashes, not inferred:
#   add/replace  docs/write-protocol-spec.md:137  (flash2: two new layers)
#   delete       docs/write-protocol-spec.md:189  (flash3: those two layers removed)
# Entry stride and field order match what READ_LAYER_LIST returns (keymap_read.read_keymap),
# which is the cross-check that they describe the same table.

LAYER_UUID_LEN = 0x10


def encode_layer_list_entries(entries: list[tuple[int, bytes, int]]) -> bytes:
    """Add or replace layers: `00` then `[idx][id][animation][10][uuid16]` each.

    NayaCore sent only the entries that CHANGED, not the whole list, so this takes a diff.
    `id` mirrors `idx` in every capture we hold.

    BYTE 2 IS THE LAYER'S LED ANIMATION. It was hardcoded to 0x00 here, which silently reset
    every layer to "solid" on any flash that wrote the list -- destroying the user's
    breathe/swirl/spectrum with nothing to show for it. It looked like a constant because every
    board we had ever captured was solid on every layer, so the byte was 0 everywhere we looked.
    A probe profile with a different effect per layer is what exposed it."""
    out = bytearray(b"\x00")
    for idx, uuid, animation in entries:
        if len(uuid) != LAYER_UUID_LEN:
            raise ValueError(f"layer {idx}: uuid must be {LAYER_UUID_LEN} bytes, got {len(uuid)}")
        if not 0 <= idx <= 0xFF:
            raise ValueError(f"layer index out of range: {idx}")
        if animation not in kr.LAYER_ANIMATIONS:
            raise ValueError(f"layer {idx}: unknown animation {animation!r}")
        out += bytes([idx, idx, animation & 0xFF, LAYER_UUID_LEN]) + uuid
    return bytes(out)


def encode_layer_list_deletes(indexes: list[int]) -> bytes:
    """Delete layers: `00` then `[idx] 00 00 00` each -- an entry with an empty id.

    The whole set is sent TWICE in one frame. That is not a typo: NayaCore did it that way, the
    device accepted it, and a single-entry form has never been tested. Deleting a layer is not
    undoable from here, so this stays byte-identical to the capture until something proves the
    shorter form works."""
    out = bytearray(b"\x00")
    for idx in list(indexes) * 2:
        if not 0 <= idx <= 0xFF:
            raise ValueError(f"layer index out of range: {idx}")
        out += bytes([idx, 0x00, 0x00, 0x00])
    return bytes(out)


def layer_uuid_bytes(uuid_str: str) -> bytes:
    """'8c113aea-ee86-...' -> the 16 raw bytes, in the order the device stores them.

    Deliberately not `uuid.UUID(...).bytes`: the device's own read path is a plain hex slice
    (`blk[4:20].hex()` re-dashed), so this mirrors that exactly rather than trusting two
    libraries to agree on byte order."""
    raw = bytes.fromhex(uuid_str.replace("-", ""))
    if len(raw) != LAYER_UUID_LEN:
        raise ValueError(f"not a 16-byte uuid: {uuid_str!r}")
    return raw


RGB_SYS = kr.RGB_SYS             # 0x09  (&rgb_ug -- the LED system keys)

# The exact inverse of keymap_read.decode_rgb_system, built from its tables so the two cannot
# drift. Without this, every LED key on a board read back was dropped at flash time and the key
# silently kept whatever it had.
_RGB_SUB_REV = {v: k for k, v in kr.RGB_SUBCOMMAND.items()}
_RGB_EFFECT_REV = {v: k for k, v in kr.RGB_EFFECTS.items()}
_RGB_COLOR_REV = {v: k for k, v in kr.RGB_COLORS.items()}


def encode_rgb_system(code: str) -> bytes:
    """LED action code -> the 8-byte 0x09 param: [subcommand u32 LE][argument u32 LE]."""
    if code in _RGB_SUB_REV:
        return encode_twoparam(_RGB_SUB_REV[code], 0)
    if code in _RGB_EFFECT_REV:
        return encode_twoparam(kr.RGB_SELECT_EFFECT, _RGB_EFFECT_REV[code])
    if code in _RGB_COLOR_REV:
        bright, sat, hue = _RGB_COLOR_REV[code]
        return encode_twoparam(kr.RGB_SET_COLOR, bright | (sat << 8) | (hue << 16))
    raise RemapEncodeError(f"unknown LED action {code!r}")


def encode_led_record(led: int, hue_deg: int, saturation: int) -> bytes:
    """[led][hue u16 LE][SATURATION].

    The third byte is saturation, not brightness -- brightness is a global setting, which is why
    the board has LED_BRIGHTNESS keys. See keymap_read.hsv_to_hex for how that was established.
    150 (UNSET_SATURATION) is a legal value here: it is the "no colour assigned" sentinel, so this
    deliberately does not clamp to 0-100."""
    return bytes([led & 0xFF]) + (hue_deg & 0xFFFF).to_bytes(2, "little") + bytes([saturation & 0xFF])


def encode_led_map(layer: int, led_records: list[bytes]) -> bytes:
    return bytes([layer]) + b"".join(led_records)


def encode_module_field(field: int, value: bytes, type_byte: int = 0x01) -> bytes:
    """[field][type][len][value]. u8 fields (speed/scroll/accel) len 1; keypress fields len 4."""
    return bytes([field, type_byte, len(value)]) + value


def encode_module_config(slot: int, field_records: list[bytes]) -> bytes:
    return bytes([slot]) + b"".join(field_records)


# --- module config: two-word records (type 0x0f) ---------------------------- #
# An 0x0f field is NOT "an axis" -- it is a record format: two LE u32s, [category][selector].
# Category 0/1/4/6 are motion axes and the selector is a direction (+1 / -1). Category 3 is
# the mouse buttons and the selector is a button bitmask (never negative, never combined).
# Confirmed against the 2026-09-02 Track Left flash; see docs/module-gestures.md.
TWO_WORD = 0x0F
MOUSE_CATEGORY = 3
# M5 = 16 proved on hardware 2026-09-06: written as category 3 selector 16 into a Tune's
# 1-finger tap, the tap drove browser FORWARD (X-button 2). M1-M4 came from a 2026-09-02 Track
# capture and could not have shown a fifth -- a Track has four buttons -- so this was the
# obvious bit continuation, and it needed testing rather than assuming.
MOUSE_MASK = {"M1": 1, "M2": 2, "M3": 4, "M4": 8, "M5": 16}
MOUSE_MASK_REV = {v: k for k, v in MOUSE_MASK.items()}


def encode_two_word(category: int, selector: int) -> bytes:
    """[category:u32le][selector:i32le] -- the 8-byte value of a type-0x0f field."""
    return (category & 0xFFFFFFFF).to_bytes(4, "little") + (selector & 0xFFFFFFFF).to_bytes(4, "little")


def decode_two_word(value: bytes) -> tuple[int, int]:
    if len(value) != 8:
        raise RemapEncodeError(f"two-word field must be 8 bytes, got {len(value)}")
    return (int.from_bytes(value[:4], "little"),
            int.from_bytes(value[4:], "little", signed=True))


def encode_mouse_button(code: str) -> bytes:
    """'M1'..'M5' -> the type-0x0f value binding a click to a Track button, Touch tap, or KEY."""
    if code not in MOUSE_MASK:
        raise RemapEncodeError(f"unknown mouse button {code!r} (expected one of {sorted(MOUSE_MASK)})")
    return encode_two_word(MOUSE_CATEGORY, MOUSE_MASK[code])


# A KEY_PRESS record whose payload is all zeros: page 0, usage 0, no modifiers, which is to
# say a keypress that presses nothing. The board carries it on the two Tune gestures NayaFlow
# labels LED Brightness Up/Down -- and it is NOT the same as an unbound field, which has record
# type NONE and no payload at all. It reads as a claimed gesture with no HID output, which is
# what an action the keyboard handles internally looks like from out here.
EMPTY_KEYPRESS = "RAW_p00:00m00"


def keypress_type(action_code: str) -> str:
    """Which encode_keypress() branch an action_code belongs in.

    A module gesture field stores an action_code and nothing else -- the action_type lives in
    the app's row, not on the device -- so the encoder has to read the shape of the code. A
    chord is the case that matters: "LCTRL + F13" has to go through the shortcut_alias branch,
    and forcing every module gesture through the plain-key branch is why a modifier could not
    be bound to one at all, despite the board carrying such records already (a stock Touch has
    LSHIFT + LALT + ESC in 0x15).
    """
    if " + " in (action_code or ""):
        return "shortcut_alias"
    if MOD_TOKEN_ALIASES.get(action_code, action_code) in MODIFIER_REV:
        return "modifier"
    return "key"


def encodable(action_code: str) -> bool:
    """Can this action_code be written into a module gesture field at all?

    Mouse buttons and anything that resolves to a keypress can. LED brightness cannot: it is in
    the action list because NayaFlow offers it, but there is no HID record for "turn the
    keyboard's own LEDs up", and the board stores EMPTY_KEYPRESS for it.
    """
    if not action_code:
        return False
    if action_code in MOUSE_MASK:
        return True
    try:
        encode_keypress(keypress_type(action_code), action_code)
        return True
    except Exception:
        return False


def decode_mouse_button(value: bytes) -> str:
    category, mask = decode_two_word(value)
    if category != MOUSE_CATEGORY:
        raise RemapEncodeError(f"category {category} is not a mouse-button record")
    if mask not in MOUSE_MASK_REV:
        raise RemapEncodeError(f"mouse mask {mask} is not one of 1/2/4/8")
    return MOUSE_MASK_REV[mask]


MODULE_SLOT_FIELDS = 40      # slot 0 is a blank template of 40 empty records


def encode_module_config_blank(slot: int, fields: int = MODULE_SLOT_FIELDS) -> bytes:
    """The payload that empties a module slot: every field as type 0, length 0.

    This is NayaFlow's own idiom, captured 2026-09-03 when it garbage-collected an unreferenced
    profile -- not type-7 clears, and not a short write (a short write is what leaves a slot
    holding a previous module's tail). It matches slot 0, which the device keeps as a blank
    template of 40 empty records.
    """
    return bytes([slot]) + b"".join(bytes([f, 0x00, 0x00]) for f in range(fields))


def encode_module_config_list(entries: list) -> bytes:
    """[00] + per-slot [slot][list_id][flag][10][uuid16], mirroring encode_layer_list.

    entries: (slot, list_id, flag, uuid16). Captured live: slot 3 -> Touch Windows with flag
    0x00 and slot 4 -> Track Left with flag 0x01, so the flag is carried rather than assumed
    (unlike the layer list, where it is always 0x00).
    """
    out = bytearray([0x00])
    for slot, list_id, module_type, uuid in entries:
        if not uuid:
            # deletion: [slot] 00 00 00, exactly what NayaFlow sent to drop a profile
            out += bytes([slot, 0x00, 0x00, 0x00])
            continue
        if len(uuid) != 16:
            raise RemapEncodeError("module-config-list uuid must be 16 bytes")
        out += bytes([slot, list_id, module_type, 0x10]) + uuid
    return bytes(out)


def encode_module_config_list_delete(slots: list) -> bytes:
    """Remove list entries. Captured form: `00` + `[slot] 00 00 00` per slot."""
    return encode_module_config_list([(s, 0, 0, b"") for s in slots])


def parse_module_config_list(payload: bytes) -> list:
    """Inverse of encode_module_config_list -> [{slot, list_id, flag, uuid}], uuid canonical
    and hyphenated so it matches module_configs.id directly."""
    out, i = [], 1                      # skip the leading 00
    while i + 4 <= len(payload):
        slot, list_id, flag, ln = payload[i:i + 4]
        i += 4
        raw = payload[i:i + ln]
        i += ln
        if ln != 16:
            continue                    # deletion / empty entry
        h = raw.hex()
        out.append({"slot": slot, "list_id": list_id, "flag": flag,
                    "uuid": f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"})
    return out


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
