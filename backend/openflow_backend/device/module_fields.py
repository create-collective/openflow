"""Module-config field map: which device field index is which gesture, per module type.

Built by correlating a real device read (flash2.pcap slots 3/4) with the installer's default
bindings (docs/reference/naya-default-module-bindings.json). Powers the module gesture UI (label
each device field) and the gesture write path (map a gesture -> its keypress field for read-modify-
write). See docs/module-gestures.md.

Confidence: TUNE is confirmed from a real read. TRACK has only axis + speed fields on the device
(no on-device gesture keypress fields — its DB shortcut bindings were never flashed). TOUCH / FLOAT
have no device read yet, so no field map — read one when the module is connected.
"""
from __future__ import annotations

import json
from pathlib import Path

_MAP: dict = json.loads((Path(__file__).with_name("module_field_map.json")).read_text())


def field_map(module_type: str) -> dict:
    """{'0x0e': {kind, gesture, ...}, ...} for a module type ('TUNE'/'TRACK'/...)."""
    return _MAP.get(module_type.upper(), {}).get("fields", {})


def gesture_fields(module_type: str) -> dict[str, int]:
    """{gesture_string: field_index} for the keypress-writable gestures of this module."""
    return {v["gesture"]: int(k, 16)
            for k, v in field_map(module_type).items()
            if v.get("kind") == "keypress" and v.get("gesture")}


# Action types that encode as a device keypress (what a keypress gesture field accepts).
KEYPRESS_ACTION_TYPES = {"key", "modifier", "shortcut_alias"}


def mouse_button_fields(module_type: str) -> dict:
    """{gesture: field_index} for the mouse-button (category-3) fields of this module type.

    These are the Track's four buttons and a Touch's tap-to-click. Confirmed writable-shaped
    from the captured Track Left flash, but no single-field write has been verified yet."""
    return {v["gesture"]: int(k, 16)
            for k, v in field_map(module_type).items()
            if v.get("kind") == "mouse_button" and v.get("gesture")}


def writable_fields(module_type: str) -> dict:
    """{gesture: field_index} for every gesture we can actually write, of any kind.

    Keypress gestures (proved live in C1: Tune 1-finger tap) plus mouse-button gestures
    (proved live in C2: a Track button rebind changed the hardware). Anything not in here
    badges app-only in the UI, which is the promise that an edit will reach the device.
    """
    return {**gesture_fields(module_type), **mouse_button_fields(module_type)}


def motion_axis_fields(module_type: str) -> dict:
    """{category: [field_index, ...]} for the motion axes (the +1/-1 direction pairs).

    A pair is one physical motion (Track: category 1 and 0 are ball X/Y, 4 is rotate).
    Inverting a motion = swapping the two selectors within its pair."""
    out: dict = {}
    for k, v in field_map(module_type).items():
        if v.get("kind") == "axis" and v.get("axis") is not None:
            out.setdefault(int(v["axis"]), []).append(int(k, 16))
    return {cat: sorted(fs) for cat, fs in sorted(out.items())}


def gesture_kind(module_type: str, behavior: str) -> str | None:
    """The device field kind for a gesture behavior string ('keypress'/'axis'/...), or None
    if that gesture has no field on the device (unknown module, or not stored on-device)."""
    for v in field_map(module_type).values():
        if v.get("gesture") == behavior:
            return v.get("kind")
    return None


# A gesture field is NOT locked to one record type -- the TYPE byte decides what it means, and
# the same field accepts either kind. Proven twice on hardware:
#   * Tune 0x08 (1-finger tap) took a keypress ("B", C1) and later a category-3 mouse button.
#   * Track 0x0b-0x0e held mouse-button masks in the stock profile and 4-byte KEYPRESSES
#     (D/R/S/T) in a second profile NayaFlow wrote on 2026-09-03.
# So "kind" records what a field currently holds, not what it can hold. This also retires the
# old claim that Track has no keypress gesture fields -- it has the same fields, and we had
# only ever seen them holding mouse masks.
MOUSE_ACTION_TYPES = {"mouse"}
CLICKABLE_KINDS = {"keypress", "mouse_button"}


def action_ok_for_kind(action_type: str, field_kind: str | None) -> bool:
    """Whether an action_type can be flashed into a field of this kind. Used to filter the
    gesture dropdown so the UI never offers something the firmware could not accept."""
    if action_type == "none":
        return True
    if field_kind in CLICKABLE_KINDS:
        return action_type in KEYPRESS_ACTION_TYPES | MOUSE_ACTION_TYPES
    if field_kind == "axis":
        return action_type == "value"
    return False  # no device field, or an action kind we have not seen written


def label_fields(module_type: str, parsed_fields: list[tuple[int, int, bytes]]) -> list[dict]:
    """Annotate a device read (list of (field, type, value)) with gesture labels for the UI.

    Returns [{field, kind, gesture, editable, value}] — `editable` marks the keypress gesture
    fields a user can rebind (custom key or a preset)."""
    fm = field_map(module_type)
    out = []
    for field, typ, val in parsed_fields:
        info = fm.get(f"0x{field:02x}", {})
        out.append({
            "field": field,
            "type": typ,
            "kind": info.get("kind", "unknown"),
            "gesture": info.get("gesture"),
            "editable": info.get("kind") == "keypress" and bool(info.get("gesture")),
            "value": val.hex(),
        })
    return out


# --- axis gestures: two fields per gesture, one per direction ---------------- #
#
# Confirmed by capture 2026-09-03: splitting horizontal:track in NayaFlow turned fields 0x07 and
# 0x08 into two INDEPENDENT keypress records ('s' and 'g'), and on the device the -1 field fired
# on a leftward swipe and the +1 field on a rightward one. So the pair is the gesture, the
# selector sign is the direction, and either half can hold any record type.
#
# Mapped explicitly rather than by category, because a category is not unique within a module:
# Touch carries two cat-4 pairs and only one of them is the 2-finger scroll.
AXIS_HALVES = {
    "TRACK": {
        "vertical:track":   {"-": 0x05, "+": 0x06, "category": 1,
                             "default": "mouse - MOUSE_DOWN - MOUSE_UP"},
        "horizontal:track": {"-": 0x07, "+": 0x08, "category": 0,
                             "default": "mouse - MOUSE_LEFT - MOUSE_RIGHT"},
        "rotate:track":     {"-": 0x0A, "+": 0x09, "category": 4,
                             "default": "mouse - SCROLL_UP - SCROLL_DOWN"},
    },
    "TUNE": {
        # THE AXES ARE THE OTHER WAY ROUND from the field order: 0x0a/0x0b are VERTICAL and
        # 0x0c/0x0d are HORIZONTAL. Which means the two scroll categories were named backwards
        # too -- category 4 is vertical scroll and category 6 is horizontal, not the reverse.
        #
        # Established on hardware 2026-09-04 by binding F17-F20 to the four halves and swiping
        # each direction: up fired the key in 0x0a, down 0x0b, left 0x0c, right 0x0d. The first
        # report of this read like a simple inversion and a straight direction swap was tried
        # first; it did not fix it, because swapping directions within the wrong axis pairing
        # cannot. Once the axes are paired correctly the SIGNS are the ordinary ones -- minus is
        # up and left -- so the encoding is unchanged from stock: 0x0a keeps selector -1.
        "vertical:tune:1_finger":   {"-": 0x0A, "+": 0x0B, "category": 4,
                                    "default": "mouse - SCROLL_UP - SCROLL_DOWN"},
        "horizontal:tune:1_finger": {"-": 0x0C, "+": 0x0D, "category": 6,
                                    "default": "mouse - SCROLL_LEFT - SCROLL_RIGHT"},
    },
    "TOUCH": {
        "vertical:touch:1_finger":    {"-": 0x05, "+": 0x06, "category": 1,
                                      "default": "mouse - MOUSE_DOWN - MOUSE_UP"},
        "horizontal:touch:1_finger":  {"-": 0x07, "+": 0x08, "category": 0,
                                      "default": "mouse - MOUSE_LEFT - MOUSE_RIGHT"},
        # Category 4 is the VERTICAL scroll pair and category 6 the HORIZONTAL one, on the Touch
        # exactly as on the Tune. Measured 2026-09-10 (create-companion census): with distinct keys
        # in all four halves, an up-swipe fired 0x0d and a down-swipe 0x0e; left fired 0x0f and
        # right 0x10. These two entries were paired the other way round until then -- the field
        # map had flagged exactly that as the open question -- so a "horizontal" binding landed on
        # vertical swipes. Signs are the ordinary ones: minus is up / left.
        "vertical:touch:2_fingers":   {"-": 0x0D, "+": 0x0E, "category": 4,
                                      "default": "mouse - SCROLL_UP - SCROLL_DOWN"},
        "horizontal:touch:2_fingers": {"-": 0x0F, "+": 0x10, "category": 6,
                                      "default": "mouse - SCROLL_LEFT - SCROLL_RIGHT"},
    },
}


# Gestures the MODULE FIRMWARE drives on its own when the field is EMPTY (type 0x07), and what
# it does then. On the wire, empty IS the default for these four -- not "unbound".
#
# Established on the Touch, 2026-09-09. NayaFlow writes all four fields empty on every flash
# (every NayaFlow-written capture we hold has them at 0x07), and a docked Touch still moves the
# cursor on one finger, left-clicks on a one-finger tap and right-clicks on a two-finger tap.
# Pinch/spread (0x11/0x12) are empty too and do NOTHING, so they are not here: for them, empty
# really is unbound. The rest of the Touch (2-finger scroll, 3-finger tap, the swipes) is stored
# explicitly, as is everything on the Track and the Tune.
#
# Why it matters both ways. The explicit records OpenFlow used to write for these -- cat 1 / cat 0
# motion, mask 1 / mask 2 -- are the coarse "definite gesture" form the Tune experiments measured
# (docs/module-field-map.md, "The Tune DOES accept pointer records"): it barely moves the cursor.
# Real cursor control on the Touch lives in its firmware and only runs when the field is empty.
# So a binding AT the default is written empty and the firmware takes over, and a read of an
# empty field decodes to the default rather than to "unbound" -- which is what made the stock
# Touch profile never read as live and minted a misleading "(on board)" capture on every read.
#
# The axis defaults must equal the matching AXIS_HALVES "default" strings.
FIRMWARE_DEFAULTS = {
    "TOUCH": {
        "tap:touch:1_finger": "M1",
        "tap:touch:2_fingers": "M2",
        "vertical:touch:1_finger": "mouse - MOUSE_DOWN - MOUSE_UP",
        "horizontal:touch:1_finger": "mouse - MOUSE_LEFT - MOUSE_RIGHT",
    },
}


def firmware_default(module_type: str, gesture: str):
    """What the module firmware does for `gesture` when its field is EMPTY, or None if empty
    means unbound for that gesture (the usual case). See FIRMWARE_DEFAULTS."""
    return FIRMWARE_DEFAULTS.get((module_type or "").upper(), {}).get(gesture)


# The firmware-driven gestures are LOCKED, as NayaFlow's own editor locks them: the field is
# always written empty, the editor shows the firmware's behaviour and offers no control, and the
# compare never counts them as drift. Whether the Touch's firmware would honour a key written
# into 0x0b / 0x05-0x08 is untested (tools/touch_one_finger_probe.py is the experiment); until
# it is, "put something else there" is a guess with the cursor as the stake. Decided 2026-09-09.
FIRMWARE_LOCKED = {t: set(g) for t, g in FIRMWARE_DEFAULTS.items()}
# Probed on hardware 2026-09-10: a keypress written into the one-finger or two-finger tap field
# reads back fine and is IGNORED -- the tap still clicks. The locks below are the firmware's,
# not a UI convention (docs/module-field-map.md, 0x0b / 0x0c).
LOCKED_REASON = "Driven by the module firmware; NayaFlow locks it too."


def gesture_locked(module_type: str, gesture: str) -> bool:
    return gesture in FIRMWARE_LOCKED.get((module_type or "").upper(), set())


# Which modules show a split checkbox on their axis rows.
#
# Track: one surface drives all three axes, so "which way did I move" is the whole question.
# Tune: its 1-finger swipes are the only motion on that module not already split -- the 2- and
# 3-finger gestures ship as separate swipe_up/down/left/right bindings.
# Touch: its 2-finger scroll axes are two device fields each (0x0d/0x0e, 0x0f/0x10), the same
# shape the Tune splits, so "two fingers up -> one key, two fingers down -> another" is exactly
# a split. It was excluded here as "no gain" because the Touch already separates 1-finger from
# 2-finger motion; that reasoning missed per-direction binding altogether (2026-09-09).
#
# The Touch's 1-finger axes are NOT splittable: the module firmware drives the cursor while
# those fields are empty (FIRMWARE_DEFAULTS), NayaFlow's own editor locks them, and whether the
# firmware honours a key written there is untested.
SPLITTABLE_TYPES = {"TRACK", "TUNE", "TOUCH"}
UNSPLITTABLE_AXES = {"TOUCH": {"vertical:touch:1_finger", "horizontal:touch:1_finger"}}

# Rendering order: the order the module is actually used in, not alphabetical.
AXIS_ORDER = ["vertical", "horizontal", "rotate"]


def splittable_axes(module_type: str) -> dict:
    """Axis gestures the UI offers a per-direction control for, in display order."""
    t = (module_type or "").upper()
    if t not in SPLITTABLE_TYPES:
        return {}
    halves = axis_halves(module_type)
    locked = UNSPLITTABLE_AXES.get(t, set())
    def rank(g):
        head = g.split(":")[0]
        return AXIS_ORDER.index(head) if head in AXIS_ORDER else len(AXIS_ORDER)
    return {g: halves[g] for g in sorted(halves, key=rank) if g not in locked}


def axis_halves(module_type: str) -> dict:
    """{gesture: {"-": field, "+": field, "category": n}} for the split-able axis gestures."""
    return AXIS_HALVES.get((module_type or "").upper(), {})


# Settings that reach the device, as {schema id: field index}.
#
# Only the ones whose identity is actually established are here, because a settings field is
# written blind -- there is no gesture to press and see. The three speeds carry their schema id
# as their label in the field map, and the two tick fields match their schema DEFAULT exactly
# on a stock module (0x06 = 75 = tick_strength, 0x07 = 1 = toggle_ticks), which is decent
# corroboration for a value we did not choose.
#
# Deliberately absent:
#   0x04  an unmapped flag sitting at 0. No idea what it does; a candidate for the 2-finger
#         repeat behaviour, and worth a probe rather than a guess.
#   0x05  identity uncertain. It was mapped as ticks_per_rotation, but that defaults to 72 and
#         bottoms out at 5 while the device stores 5 -- an odd floor. Setting it to 100 made the
#         detents SOFTER and further apart, so it reads as tick spacing, not a count. Writing a
#         "ticks per rotation" of 72 into a spacing field would be a guess with a feel penalty.
SETTING_FIELDS = {
    "TOUCH": {"pointer_speed": 0x00, "scroll_speed": 0x01, "pointer_accel": 0x02,
              "pointer_accel_on": 0x03},
    "TRACK": {"pointer_speed": 0x00, "scroll_speed": 0x01, "pointer_accel": 0x02,
              "pointer_accel_on": 0x03},
    "TUNE": {"pointer_speed": 0x00, "scroll_speed": 0x01, "pointer_accel": 0x02,
             "pointer_accel_on": 0x03, "tick_strength": 0x06, "toggle_ticks": 0x07},
}

# Settings the app shows but cannot yet write, so the UI can say so instead of implying it did.
UNWRITABLE_SETTINGS = {"TUNE": {"ticks_per_rotation"}}


def setting_fields(module_type: str) -> dict:
    """{schema id: field index} for the settings a flash can actually write."""
    return SETTING_FIELDS.get((module_type or "").upper(), {})


def setting_is_writable(module_type: str, setting_id: str) -> bool:
    return setting_id in setting_fields(module_type)


# Settings the app stores as booleans; on the wire they are the same one-byte field as the rest.
TOGGLE_SETTINGS = {"pointer_accel_on", "toggle_ticks"}
_ONE_BYTE = 0x01      # the record type a setting field carries (module_layout.encode_setting)


def decode_settings(module_type: str, fields: dict) -> dict:
    """{setting id: value} for the setting fields a slot actually holds, typed the way the app
    stores them: int for sliders, bool for toggles.

    The inverse of module_layout.encode_setting. Read off the reference board 2026-09-11: every
    module carries pointer speed 10 / accel 50 / accel on at 0x00-0x03, a Touch stores scroll
    speed 50 where a Track or Tune stores 10, and the Tune adds tick strength 75 and ticks on at
    0x06 / 0x07. Only a one-byte 0x01 record counts; anything else in a setting index (a Track's
    axis two-words at 0x05-0x07, an empty field) is not a setting value and is left out.
    """
    out = {}
    for sid, idx in setting_fields(module_type).items():
        rec = fields.get(idx)
        if not rec:
            continue
        typ, val = rec
        if typ != _ONE_BYTE or len(val) != 1:
            continue
        out[sid] = bool(val[0]) if sid in TOGGLE_SETTINGS else int(val[0])
    return out


def motion_name(module_type: str, field: int, category: int, selector: int):
    """The action_code a two-word MOTION record in an axis field stands for, or None.

    An axis half's default record is (category, +/-1) and the pair's two names live in the
    gesture's `default` string as "mouse - <minus> - <plus>". Decoding through that keeps one
    source of truth: the names the encoder writes are the names the reader gives back.
    """
    for h in axis_halves(module_type).values():
        if field not in (h["-"], h["+"]) or category != h["category"]:
            continue
        names = split_pair(h["default"])
        if None in names:
            return None
        for i, sign in enumerate(("-", "+")):
            if half_selector(h, sign) == selector:
                return names[i]
        return None
    return None


def half_selector(half: dict, sign: str) -> int:
    """The motion selector the DEVICE stores for one half of an axis.

    Usually the sign itself, but not always: on the Tune scroll axes the half that fires on a
    right swipe is the one holding selector -1. Keeping this separate from the sign is what lets
    a direction label be corrected without changing a single byte of what gets flashed.
    """
    return (half.get("selectors") or {}).get(sign, -1 if sign == "-" else 1)


def axis_fields(module_type: str) -> dict:
    """{field index: (gesture, half)} -- the inverse, for decoding a slot."""
    out = {}
    for gesture, h in axis_halves(module_type).items():
        out[h["-"]] = (gesture, "-")
        out[h["+"]] = (gesture, "+")
    return out


# Gestures the app can express but the DEVICE has no field for. A Track's 15 fields are fully
# accounted for without hold (capture 2026-09-03: NayaFlow wrote the hold value over the tap and
# the tap never reached the board), so offering both is offering to lose one.
UNBACKED_GESTURES = {
    "TRACK": {f"hold:track:button_{i}" for i in (1, 2, 3, 4)},
}


def gesture_has_device_field(module_type: str, behavior: str) -> bool:
    """Whether a gesture can actually reach the hardware."""
    t = (module_type or "").upper()
    if behavior in UNBACKED_GESTURES.get(t, ()):
        return False
    # A combined pair reaches the device as its two halves, so it is backed if they are.
    pair = paired_gestures(t).get(behavior)
    if pair:
        return all(h in writable_fields(t) for h in pair.values())
    return behavior in writable_fields(t) or behavior in axis_halves(t)


# Gestures made of a PAIR of fields whose halves are plain keypresses rather than motion
# records. The Tune dial is the case: its combined binding is "C_VOL_DOWN - C_VOL_UP" and the
# two values sit in 0x23 and 0x22, so the pair is real even though neither half is an axis.
PAIRED_GESTURES = {
    "TUNE": {
        "rotate:tune:dial": {"-": "counter_clockwise_rotate:tune:dial",
                             "+": "clockwise_rotate:tune:dial"},
    },
}


def paired_gestures(module_type: str) -> dict:
    """{combined gesture: {"-": half gesture, "+": half gesture}}."""
    return PAIRED_GESTURES.get((module_type or "").upper(), {})


def pair_halves(module_type: str) -> dict:
    """{half gesture: (combined gesture, sign)} -- the inverse of paired_gestures."""
    return {g: (combined, sign)
            for combined, halves in paired_gestures(module_type).items()
            for sign, g in halves.items()}


def split_pair(code):
    """The two direction values in a combined binding, as (minus, plus).

    Two spellings are in use and both have to parse: a motion axis writes
    "mouse - MOUSE_DOWN - MOUSE_UP" while the dial writes "C_VOL_DOWN - C_VOL_UP" with no
    leading kind. Taking the LAST TWO parts handles both -- dropping the first part instead
    reads the dial's minus value as its plus and loses the other.
    """
    if not code or " - " not in str(code):
        return (None, None)
    parts = [p.strip() for p in str(code).split(" - ")]
    return (parts[-2], parts[-1]) if len(parts) >= 2 else (None, None)
