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
        "horizontal:touch:2_fingers": {"-": 0x0D, "+": 0x0E, "category": 4,
                                      "default": "mouse - SCROLL_LEFT - SCROLL_RIGHT"},
        "vertical:touch:2_fingers":   {"-": 0x0F, "+": 0x10, "category": 6,
                                      "default": "mouse - SCROLL_UP - SCROLL_DOWN"},
    },
}


# Which modules show a split checkbox on their axis rows.
#
# Track: one surface drives all three axes, so "which way did I move" is the whole question.
# Tune: its 1-finger swipes are the only motion on that module not already split -- the 2- and
# 3-finger gestures ship as separate swipe_up/down/left/right bindings.
#
# Touch is excluded on merit: it already names 1-finger and 2-finger motion as separate
# gestures, so a split there would show two horizontals and two verticals for no gain.
SPLITTABLE_TYPES = {"TRACK", "TUNE"}

# Rendering order: the order the module is actually used in, not alphabetical.
AXIS_ORDER = ["vertical", "horizontal", "rotate"]


def splittable_axes(module_type: str) -> dict:
    """Axis gestures the UI offers a per-direction control for, in display order."""
    if (module_type or "").upper() not in SPLITTABLE_TYPES:
        return {}
    halves = axis_halves(module_type)
    def rank(g):
        head = g.split(":")[0]
        return AXIS_ORDER.index(head) if head in AXIS_ORDER else len(AXIS_ORDER)
    return {g: halves[g] for g in sorted(halves, key=rank)}


def axis_halves(module_type: str) -> dict:
    """{gesture: {"-": field, "+": field, "category": n}} for the split-able axis gestures."""
    return AXIS_HALVES.get((module_type or "").upper(), {})


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
