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

    # A new slot needs a structurally complete config, which only an existing one can supply.
    claimed = [cid for cid in slot_for
               if cid not in existing and cid not in allocated]
    templates = {}
    for cid in allocated + claimed:
        typ = config_types.get(cid)
        if cid in claimed:
            # A capture already IS the config in the slot it is claiming, so it templates from
            # that slot rather than from some other profile of the same type. If its bindings
            # still match, the overlay comes out identical and no config write is needed.
            src = device_slots.get(slot_for[cid]) or device_slots.get(str(slot_for[cid]))
        else:
            src = _template_slot(typ, config_types, existing, device_slots)
        if src is None:
            raise LayoutError(
                "cannot add a %s profile: nothing of that type is on the keyboard to copy a "
                "complete config from. Dock the module and read the keyboard first."
                % (typ or "module"))
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
            "claimed": claimed}


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


def _template_slot(module_type, config_types, existing, device_slots):
    """A slot of the same module type whose fields we can copy.

    Prefers the SMALLEST, which is the one without trailing junk from a previous config: Track
    Left is 15 fields and Track Right 36, and copying the latter would carry 21 orphaned fields
    into the new slot.
    """
    best = None
    for cid, slot in existing.items():
        if config_types.get(cid) != module_type:
            continue
        fields = device_slots.get(slot)
        if fields is None:
            fields = device_slots.get(str(slot))
        if not fields:
            continue
        if best is None or len(fields) < len(best):
            best = fields
    return best


def overlay(template, module_type, bindings):
    """A complete config: the template's fields with the profile's gestures written over it.

    `bindings` is {gesture: action_code}. Only gestures in writable_fields are applied -- every
    other field passes through untouched, which is the whole point of templating.
    """
    out = dict(template)
    for gesture, idx in module_fields.writable_fields(module_type).items():
        code = bindings.get(gesture)
        if not code:
            continue
        rec = _encode_gesture(idx, code)
        if rec is not None:
            out[idx] = rec
    return out


def _encode_gesture(idx, code):
    """(type, value) for one gesture field, or None if we cannot encode it safely.

    A gesture field is NOT type-locked -- the same index holds a mouse-button mask or a keypress
    depending on the record type, proved by a Track profile whose four buttons were bound to
    letters. So the action code decides the form.
    """
    if code in R.MOUSE_MASK:
        return (R.TWO_WORD, R.encode_two_word(R.MOUSE_CATEGORY, R.MOUSE_MASK[code]))
    try:
        return (R.KEY_PRESS, R.encode_keypress("key", code))
    except Exception:
        return None


def _uuid16(cid):
    return bytes.fromhex(cid.replace("-", ""))
