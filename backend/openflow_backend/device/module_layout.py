"""Turn per-layer bay assignments into the slots, list entries and configs to flash.

Layers do not hold module profiles; they hold a SLOT NUMBER per bay, and a separate
module-config list says which profile each slot is. So "layer 1 uses a different Track profile"
is really three coordinated writes, captured from NayaFlow on 2026-09-03:

    WRITE_LAYER_DATA         014c0500              layer 1, bay 0x4c -> slot 5
    WRITE_MODULE_CONFIG_LIST 00 05 05 01 10 <uuid> add entry: slot 5, type 1 (Track)
    WRITE_MODULE_CONFIG_DATA 05 ...                the config itself

This module works out that plan. The rules it encodes were observed, not assumed:

* A new slot is ALLOCATED, never reused. Slots already carrying a profile came back with 0
  fields changed, so an existing uuid keeps its slot and only genuinely new profiles take a
  fresh index. Slot numbers are not stable across flashes, which is why everything here is
  resolved by uuid.
* Non-overriding layers write 0x78 (inherit), which resolves to the BASE layer -- not to the
  nearest layer below. Proved by overriding a bay on layer 1 and pressing the buttons on
  layer 2.
* A config is templated from one already on the device. We model 4 of a Track's 15 fields;
  authoring one from the DB alone would drop its motion axes and speeds and leave a module
  that does not work. So a new slot starts as a copy of an existing config of the same type,
  and only the gesture fields we understand are overlaid.
"""
from __future__ import annotations

from . import module_fields, remap as R

BAY_INHERIT = 0x78

# Bay positions in layer data: 4 module types x 2 sides (docs/phase-c-test-plan.md).
BAY_POSITIONS = {
    "TOUCH": {"left": 0x4A, "right": 0x4B},
    "TRACK": {"left": 0x4C, "right": 0x4D},
    "TUNE": {"left": 0x4E, "right": 0x4F},
    "FLOAT": {"left": 0x50, "right": 0x51},
}
# binding_location strings as stored in module_config_bindings / returned by decode_bays.
LOCATION_TO_POSITION = {
    "%s:keyboard_%s" % (t.lower(), side): pos
    for t, sides in BAY_POSITIONS.items()
    for side, pos in sides.items()
}

# The list entry's type byte. Track is 1, captured directly; the others follow MODULE_TYPES.
MODULE_TYPE_CODE = {"TOUCH": 0, "TRACK": 1, "TUNE": 2, "FLOAT": 3}


class LayoutError(Exception):
    """The requested layout cannot be flashed safely."""


def list_types(list_hex) -> dict:
    """{slot: module type} from the module LIST's per-entry type byte.

    The list is the one place the board states what each slot IS. It is what lets a slot whose
    uuid the app has never seen -- every slot NayaFlow wrote, since its uuids are its own -- be
    used as a template for a new profile of that type, and be compared by content on a read,
    instead of being treated as a slot of unknown type."""
    if not list_hex:
        return {}
    by_code = {code: typ for typ, code in MODULE_TYPE_CODE.items()}
    try:
        entries = R.parse_module_config_list(bytes.fromhex(list_hex))
    except ValueError:
        return {}
    return {e["slot"]: by_code[e["flag"]] for e in entries if e["flag"] in by_code}


def plan(bays_by_layer, config_types, device_list, device_slots, base_order=0,
         captured_from=None):
    """Work out the module layout to flash.

    bays_by_layer: {layer order: {binding_location: config uuid}}  -- what the app wants.
    config_types:  {config uuid: module type}                      -- from module_configs.
    device_list:   parse_module_config_list(...) of the list currently on the device.
    device_slots:  {slot: {field: (type, value)}}                  -- current slot contents.
    captured_from: {config uuid: the device uuid it was captured from}, so a capture claims the
                   slot it was taken from instead of stranding it.

    Returns {slot_for, list_entries, templates, bays, allocated}.
    """
    base = bays_by_layer.get(base_order, {})
    referenced = {cid for bays in bays_by_layer.values() for cid in bays.values()
                  if cid and cid not in ("transparent", "disabled")}

    existing = {e["uuid"]: e["slot"] for e in device_list}
    # What the board says each slot holds, from the list's type byte, keyed like `existing`.
    # Needed for templating: a slot NayaFlow wrote carries a uuid no profile of ours has, so
    # config_types knows nothing about it, and without this a docked, fully readable Touch
    # counted as "nothing of that type on the keyboard" (seen 2026-09-10).
    board_types = {e["uuid"]: e["type"] for e in device_list if e.get("type")}
    slot_for = {cid: existing[cid] for cid in referenced if cid in existing}

    # A capture has its own uuid but IS the config in the slot it was taken from, so it claims
    # that slot rather than allocating a new one and leaving the original stranded. If the
    # profile it was captured FROM is also referenced, that one owns the slot by identity and
    # the capture falls through to a fresh index.
    for cid in sorted(referenced - set(slot_for)):
        src = (captured_from or {}).get(cid)
        if src and src in existing and src not in referenced and existing[src] not in slot_for.values():
            slot_for[cid] = existing[src]

    # Allocate the lowest free index for profiles the board does not carry yet. Slot 0 is the
    # blank template, so allocation starts at 1.
    taken = set(existing.values()) | set(slot_for.values())
    allocated = []
    for cid in sorted(referenced - set(slot_for)):
        n = 1
        while n in taken:
            n += 1
        slot_for[cid] = n
        taken.add(n)
        allocated.append(cid)

    # Every referenced profile is templated, not just newly placed ones.
    #
    # A slot already carrying this uuid used to be left completely alone, on the theory that it
    # was already correct. It is not: the app's copy drifts from the board (an edit that was
    # never flashed, a field the device has cleared), and skipping it meant a flash silently
    # refused to push your own bindings. The caller compares the overlay against the slot and
    # writes only when it actually differs, so an unchanged profile still sends nothing.
    claimed = [cid for cid in slot_for
               if cid not in existing and cid not in allocated]
    kept = [cid for cid in slot_for if cid in existing]
    templates = {}
    for cid in allocated + claimed + kept:
        typ = config_types.get(cid)
        if cid in claimed or cid in kept:
            # A capture already IS the config in the slot it is claiming, so it templates from
            # that slot rather than from some other profile of the same type. If its bindings
            # still match, the overlay comes out identical and no config write is needed.
            src = device_slots.get(slot_for[cid]) or device_slots.get(str(slot_for[cid]))
        else:
            src = _template_slot(typ, config_types, existing, device_slots, board_types)
        if src is None:
            if cid in allocated:
                # A genuinely new slot cannot be written without a complete config to copy: a
                # partial write leaves the module missing fields we do not model.
                raise LayoutError(
                    "cannot add a %s profile: nothing of that type is on the keyboard to copy a "
                    "complete config from. Dock the module and read the keyboard first."
                    % (typ or "module"))
            # A slot already on the board whose contents we could not read: leave it exactly as
            # it is rather than writing a config assembled from nothing.
            continue
        templates[cid] = src

    list_entries = []
    for cid in sorted(referenced, key=lambda c: slot_for[c]):
        typ = config_types.get(cid)
        code = MODULE_TYPE_CODE.get(typ)
        if code is None:
            raise LayoutError("unknown module type %r for profile %s" % (typ, cid))
        list_entries.append((slot_for[cid], slot_for[cid], code, _uuid16(cid)))

    return {"slot_for": slot_for, "list_entries": list_entries, "templates": templates,
            "bays": _bays(bays_by_layer, base, slot_for, base_order), "allocated": allocated,
            "claimed": claimed, "kept": kept}


def _bays(bays_by_layer, base, slot_for, base_order):
    """{layer order: {bay position: slot | 0x78}}.

    The base layer names its slots outright; every other layer inherits unless it genuinely
    differs. That is both what NayaFlow writes and what makes an edit to the base layer
    propagate across the other layers on the board itself.
    """
    out = {}
    for order, bays in bays_by_layer.items():
        row = {}
        for location, cid in bays.items():
            pos = LOCATION_TO_POSITION.get(location)
            if pos is None:
                continue
            if cid == "disabled":
                row[pos] = 0
            elif not cid or cid == "transparent":
                row[pos] = BAY_INHERIT
            elif order != base_order and base.get(location) == cid:
                row[pos] = BAY_INHERIT      # same as base: let the board resolve it
            else:
                row[pos] = slot_for[cid]
        out[order] = row
    return out


def _template_slot(module_type, config_types, existing, device_slots, board_types=None):
    """A slot of the same module type whose fields we can copy.

    Prefers the SMALLEST, which is the one without trailing junk from a previous config: Track
    Left is 15 fields and Track Right 36, and copying the latter would carry 21 orphaned fields
    into the new slot.

    A slot's type comes from the board's own list byte first (`board_types`), then from the
    app's profile of that uuid. The board's word wins because it is the slot's CONTENTS being
    copied, and it is the only source for a slot whose uuid the app does not hold.
    """
    best = None
    for cid, slot in existing.items():
        if ((board_types or {}).get(cid) or config_types.get(cid)) != module_type:
            continue
        fields = device_slots.get(slot)
        if fields is None:
            fields = device_slots.get(str(slot))
        if not fields:
            continue
        if best is None or len(fields) < len(best):
            best = fields
    return best


def encode_setting(value) -> tuple:
    """(type, value) for a settings field.

    These are ONE byte with record type 0x01 -- the same type byte a keypress uses, with a
    different length. Read straight off a stock module: 0x00 = 0a (pointer speed 10), 0x07 = 01
    (ticks on). Writing four bytes here because "type 0x01 means keypress" would be writing a
    keypress into a speed field.
    """
    if isinstance(value, bool):
        n = 1 if value else 0
    elif isinstance(value, str):
        v = value.strip().lower()
        n = 1 if v == "true" else 0 if v == "false" else int(float(v))
    else:
        n = int(value)
    return (R.KEY_PRESS, bytes([max(0, min(255, n))]))


def overlay(template, module_type, bindings, axes=None, settings=None):
    """A complete config: the template's fields with the profile's gestures written over it.

    `bindings` is {gesture: action_code} for single-field gestures.
    `axes` is {gesture: {"minus": code|None, "plus": code|None, "invert": bool}} for the axis
    gestures, which occupy TWO fields each.

    Every other field passes through untouched, which is the whole point of templating.
    """
    out = dict(template)
    for gesture, idx in module_fields.writable_fields(module_type).items():
        # "absent from bindings" and "present but unbound" are different instructions and were
        # collapsed into one `if not code: continue`. So unbinding a gesture in the UI was a
        # no-op on the board: the template's old value passed straight through and the field
        # kept whatever it had.
        if gesture not in bindings:
            continue                       # not managed here -- the template owns this field
        code = bindings[gesture]
        if not code:
            # Explicitly unbound -> the NONE record, empty value. Captured from NayaCore twice:
            # `01 0b 07 00` (the "enable all modules" flash that silently cleared Track Right
            # button 1) and `08 07 00` in the flash-3 table. flash.py already emits this exact
            # record for stale fields.
            out[idx] = (R.NONE_BEH, b"")
            continue
        if module_fields.gesture_locked(module_type, gesture):
            # FIRMWARE-DRIVEN -> ALWAYS EMPTY, whatever the row says, and the module firmware
            # takes over. The explicit record (mask 1 for the Touch's one-finger tap) is what
            # was written here until 2026-09-09; it is not what NayaFlow writes, and for the
            # cursor gestures the explicit form is the coarse motion the Tune experiments
            # measured. A key stored on one of these rows (an old edit) is not written either:
            # whether the firmware would honour it is untested, and NayaFlow locks the field.
            # See module_fields.FIRMWARE_DEFAULTS / FIRMWARE_LOCKED.
            out[idx] = (R.NONE_BEH, b"")
            continue
        rec = _encode_gesture(idx, code)
        if rec is not None:
            out[idx] = rec
    for gesture, spec in (axes or {}).items():
        for idx, rec in encode_axis(module_type, gesture, spec).items():
            out[idx] = rec
    # Settings were never written at all: set_module_setting stored them in the app and the
    # overlay copied the device's own values straight back, so every slider on the Modules page
    # silently did nothing to the keyboard.
    fields = module_fields.setting_fields(module_type)
    for sid, value in (settings or {}).items():
        idx = fields.get(sid)
        if idx is None:
            continue                    # not one we can place; see SETTING_FIELDS
        try:
            out[idx] = encode_setting(value)
        except (TypeError, ValueError):
            continue                    # a value we cannot make a byte of: leave the board's
    return out


def encode_axis(module_type, gesture, spec):
    """{field: (type, value)} for one axis gesture's two halves.

    A half holding a pointer/scroll action stays a two-word record whose SELECTOR SIGN is the
    direction; a half bound to a key becomes a keypress record instead, which is exactly what
    NayaFlow wrote when the gesture was split (capture 2026-09-03).

    `invert` flips the two signs. That is the whole of it at the device level -- there is no
    invert flag anywhere in the config, and NayaFlow never wrote one, which is why its own invert
    control does nothing.
    """
    half = module_fields.axis_halves(module_type).get(gesture)
    if half is None:
        return {}
    category = half["category"]
    invert = bool(spec.get("invert"))
    if module_fields.gesture_locked(module_type, gesture):
        # The Touch's one-finger cursor: BOTH halves EMPTY, always, so the firmware's own cursor
        # control runs. Writing the explicit cat 1 / cat 0 motion records here -- which this did
        # for every stock profile until 2026-09-09 -- replaces real cursor control with the
        # coarse "definite gesture" motion the Tune experiments measured. These axes are locked
        # (not splittable, not invertible), so `spec` cannot ask for anything else; if an old
        # row does, it is still not written.
        return {half["-"]: (R.NONE_BEH, b""), half["+"]: (R.NONE_BEH, b"")}
    out = {}
    for sign, key in (("-", "minus"), ("+", "plus")):
        idx = half[sign]
        code = spec.get(key)
        if code:
            rec = _encode_gesture(idx, code)     # a key bound to this half
            if rec is not None:
                out[idx] = rec
                continue
        # The selector belongs to the HALF, not to the sign. On the Tune scroll axes the half
        # that fires on a right swipe is the one holding -1, so deriving the selector from the
        # sign would rewrite the board's motion records the moment a direction label was fixed.
        selector = module_fields.half_selector(half, sign)
        if invert:
            selector = -selector
        out[idx] = (R.TWO_WORD, R.encode_two_word(category, selector))
    return out


def _encode_gesture(idx, code):
    """(type, value) for one gesture field, or None if we cannot encode it safely.

    A gesture field is NOT type-locked -- the same index holds a mouse-button mask or a keypress
    depending on the record type, proved by a Track profile whose four buttons were bound to
    letters. So the action code decides the form.
    """
    if code in R.MOUSE_MASK:
        return (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, R.MOUSE_MASK[code]))
    if not R.encodable(code):
        # LED brightness and friends. The board already carries an empty keypress on those
        # gestures, and the template passes it through untouched -- writing something of our
        # own invention over it would be a guess about firmware we have not seen.
        return None
    # The branch is chosen from the shape of the code, not hardcoded to "key". Hardcoding it
    # meant a chord never reached the shortcut_alias branch, so no modifier could be bound to
    # any module gesture -- while the board itself carries such records (stock Touch 0x15 is
    # LSHIFT + LALT + ESC).
    return (R.KEY_PRESS, R.encode_keypress(R.keypress_type(code), code))


def _uuid16(cid):
    return bytes.fromhex(cid.replace("-", ""))
