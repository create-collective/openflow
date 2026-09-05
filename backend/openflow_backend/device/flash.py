"""Flash orchestration for the Naya Create — build a write plan and (optionally) send it.

The inverse of the read path, one level up from `remap.py`'s encoders. Turns a desired
board state (from the OpenFlow DB, or from a device read for round-trip testing) into the
ordered WRITE sequence NayaCore uses, chunk-framed and ready to send — or, in dry-run,
just the frames + a diff summary and nothing on the wire.

Write order (from the captured flashes, docs/write-protocol-spec.md), all to dest 0x50:
  WRITE_LAYER_LIST (only if layers added/removed)
  -> WRITE_LAYER_DATA per changed layer
  -> WRITE_MODULE_CONFIG_DATA per changed slot
  -> WRITE_LED_MAP per changed layer
  -> SYSTEM SET_TIMEOUTS (only if timeouts changed)
  -> verification reads + diff

Everything here is dry unless `flash(..., dry_run=False)` is called with a live transport.
Module GESTURE bindings are intentionally NOT written — see MODULE CONFIDENCE below.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

from .._vendor.nayactl.constants import CAT_SYSTEM
from . import module_fields as MF
from . import remap as R

FULL_LAYER_POSITIONS = range(0x00, 0x52)     # 82 positions = whole board + module slots
# A key's double-tap and tap+hold live in a SECOND bank of the same 82 positions, offset by
# 0x52 (confirmed live: pos 0x49 tap/hold, pos 0x9b double-tap/tap+hold on the same key).
SECOND_BANK = 0x52
# The second bank is 74 positions (0x52-0x9b), not another 82: the 8 module slots at
# 0x4A-0x51 have no double-tap. 82 + 74 = 156, which is exactly the record count the device
# returns for a layer, and 0x9b is the highest position it reports.
SECOND_BANK_KEYS = range(0x00, 0x4A)
ALL_LAYER_POSITIONS = range(0x00, 0x9C)
LED_COUNT = 88                                # 0x00..0x57 (observed full LED map = 136? see note)
SYS_SET_TIMEOUTS = 0x100A

# ---- MODULE CONFIDENCE ------------------------------------------------------------------
# Captured WRITE evidence exists only for these module-config fields, so only these are
# safe to encode/flash. Everything else (the type-0x0f (axis,direction) gesture fields, the
# 0x03/0x04 flags) is passed through UNCHANGED and never rewritten. Multi-finger gesture ->
# action bindings are NOT written: their device encoding is unconfirmed (read-only, no
# captured write; NayaFlow's own gesture editor is incomplete). See flash notes / the plan.
MODULE_SAFE_FIELDS = {
    0x00: ("pointer_speed", "u8"),
    0x01: ("scroll_speed", "u8"),
    0x02: ("pointer_accel", "u8"),
    0x08: ("one_finger_tap", "keypress"),
}


# --------------------------------------------------------------------------- #
# desired state                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class DesiredState:
    """Everything a flash can set. `layers`/`leds` are keyed by device layer index."""
    layers: dict[int, dict[int, tuple[int, bytes]]] = field(default_factory=dict)   # idx -> {pos: (type, param)}
    leds: dict[int, dict[int, tuple[int, int]]] = field(default_factory=dict)        # idx -> {led: (hue, value)}
    modules: dict[int, dict[int, tuple[int, bytes]]] = field(default_factory=dict)   # slot -> {field: (type, value)}
    timeouts: tuple[int, int, int] | None = None                                     # (idle, sleep, sleep_batt) ms
    layer_uuids: dict[int, bytes] = field(default_factory=dict)                       # idx -> 16-byte id (add/delete)
    profile_id: str | None = None                                                     # which profile this came from
    # {slot: (list_id, module_type, uuid16)} -- the module-config LIST the app intends.
    # None means the app is not managing the module set, and NOTHING is garbage collected.
    # That distinction matters: desired.modules is empty today, so a naive "anything on the
    # device we do not want is an orphan" rule would wipe every module config on the board.
    module_list: dict[int, tuple[int, int, bytes]] | None = None


def desired_from_read(read_json: dict) -> DesiredState:
    """Build the desired state from a device read (raw_records + led). Faithful: uses the
    exact bytes the board returned, so a re-flash round-trips (Phase B / round-trip test)."""
    d = DesiredState()
    for k, recs in read_json["raw_records"].items():
        idx = int(k)
        d.layers[idx] = {}
        for pos, typ, param_hex in recs:
            if pos in FULL_LAYER_POSITIONS:
                d.layers[idx][pos] = (typ, bytes.fromhex(param_hex))
    led = read_json.get("led") or {}
    for k, entries in led.items():
        idx = int(k)
        d.leds[idx] = {int(i): (int(h), int(v)) for i, h, v in entries}
    return d


def _hex_to_hue_val(hex_color: str) -> tuple[int, int]:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, _s, v = colorsys.rgb_to_hsv(r, g, b)
    return round(h * 360) % 360, round(v * 100)


def desired_from_device_read(read: dict) -> DesiredState:
    """DeviceService.read_keymap output -> DesiredState, for use as `current` in a flash.

    A flash needs this, not just the DB: compute_plan uses `current` both to carry through
    state the app does not model (the module->dock bindings at layer positions 0x4A-0x51) and
    to know which module fields to clear. Flashing without a fresh read would unassign every
    module -- see tests/test_flash_preserve.py."""
    d = DesiredState()
    for idx, recs in (read.get("layers") or {}).items():
        d.layers[int(idx)] = {pos: (typ, bytes(param)) for pos, typ, param in recs
                              if pos in ALL_LAYER_POSITIONS}
    for idx, entries in (read.get("led") or {}).items():
        d.leds[int(idx)] = {i: (hue, val) for i, hue, val in entries}
    return d


class AmbiguousProfileError(ValueError):
    """More than one profile exists and the caller did not say which one to flash."""


def _resolve_profile(conn, profile_id: str | None) -> str:
    """Which profile to flash. Never guessed.

    The layers table spans every profile, so flashing without scoping it writes whichever
    profile the query happened to return last -- a different keymap each time the DB changes.
    `state = 'ON_BOARD'` is not a usable marker either: importing a read sets it, so several
    profiles claim it at once.
    """
    rows = [dict(r) for r in conn.execute("SELECT id, name FROM profiles ORDER BY order_id, name")]
    if profile_id is not None:
        if not any(r["id"] == profile_id for r in rows):
            raise ValueError(f"no profile {profile_id}")
        return profile_id
    if len(rows) == 1:
        return rows[0]["id"]
    raise AmbiguousProfileError(
        f"{len(rows)} profiles exist; say which one to flash. "
        + ", ".join(f'{r["name"]!r} ({r["id"]})' for r in rows))


def desired_from_db(conn, profile_id: str | None = None) -> DesiredState:
    """Build the desired state from the OpenFlow DB (the DB->device mapping).

    Layers/keys/key_bindings -> binding records; keys.color_hex -> LED map; module_configs +
    the SAFE module fields; settings (correlation ids) -> timeouts + tapping term/flavour.
    Gesture bindings are deliberately skipped (see MODULE CONFIDENCE)."""
    d = DesiredState()
    term, flavour = _read_term_flavour(conn)
    pid = _resolve_profile(conn, profile_id)
    d.profile_id = pid
    layer_order = {row["id"]: row["order_id"] for row in
                   conn.execute("SELECT id, order_id FROM layers WHERE profile_id = ?", (pid,))}
    for lrow in conn.execute(
            "SELECT id, order_id FROM layers WHERE profile_id = ? ORDER BY order_id", (pid,)):
        idx = lrow["order_id"]
        d.layers[idx], d.leds[idx] = {}, {}
        q = conn.execute(
            "SELECT k.position_id p, k.color_hex, b.action_type at, b.action_code ac, b.behavior beh "
            "FROM keys k LEFT JOIN key_bindings b ON b.key_id = k.id WHERE k.layer_id = ? ORDER BY k.position_id",
            (lrow["id"],))
        # group multiple binding rows per position (tap+hold)
        by_pos: dict[int, list] = {}
        colors: dict[int, str] = {}
        for r in q:
            if r["p"] is None or r["p"] not in FULL_LAYER_POSITIONS:
                continue
            if r["color_hex"]:
                colors[r["p"]] = r["color_hex"]
            if r["at"] is not None:
                by_pos.setdefault(r["p"], []).append(r)
        for pos, rows in by_pos.items():
            rec = _binding_rows_to_record(rows, term, flavour, layer_order)
            if rec is not None:
                d.layers[idx][pos] = rec
            # double-tap / tap+hold are a second hold-tap record at pos + 0x52
            second = _second_bank_record(rows, term, flavour)
            if second is not None:
                d.layers[idx][pos + SECOND_BANK] = second
        for pos, hexc in colors.items():
            if len(hexc) == 7 and hexc[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in hexc[1:]):
                d.leds[idx][pos] = _hex_to_hue_val(hexc)
    d.timeouts = _read_timeouts(conn)
    d.modules = _read_module_safe_fields(conn)
    return d


# --- DB -> record helpers (semantic; the interesting mapping) --------------- #

def _binding_rows_to_record(rows: list, term: int, flavour: int, layer_order: dict) -> tuple[int, bytes] | None:
    """One position's binding row(s) -> (type, param). Handles key/modifier/shortcut, layer
    switches, bluetooth, and tap+hold (a 'press' row + a 'hold' row)."""
    press = next((r for r in rows if r["beh"] in ("press", "tap", None)), rows[0])
    hold = next((r for r in rows if r["beh"] == "hold"), None)
    at, code = press["at"], press["ac"]

    if hold is not None:
        # OneKey (0x10), not the home-row 0x03 form. Both are hold-tap records with the same
        # body, but the type encodes intent and 0x10 is what NayaFlow writes for a user-created
        # tap+hold -- it is what sits on the board, and what the secondary bank uses. Emitting
        # 0x03 here made a re-flash of a profile READ FROM the device rewrite those two keys.
        tap_kp = R.encode_keypress(at, code)
        hold_kp = R.encode_keypress(hold["at"], hold["ac"])
        return R.HOLD_TAP_ONEKEY, R.encode_holdtap_param(R.HOLD_TAP_ONEKEY, flavour, term, hold_kp, tap_kp)

    if at in ("key", "modifier", "shortcut_alias"):
        return R.KEY_PRESS, R.encode_keypress(at, code)
    if at == "bluetooth":
        prof = R.BT_PROFILE_REV.get(code)
        if prof is not None:
            return R.TWO_PARAM, R.encode_twoparam(3, prof)
        return None
    if at in ("layer_polite_hold",):
        order = _target_order(code, layer_order)
        return None if order is None else (R.LAYER_HOLD, R.encode_layer_param(order))
    if at in ("layer_rude_toggle",):
        order = _target_order(code, layer_order)
        return None if order is None else (R.LAYER_TO, R.encode_layer_param(order))
    if at in ("layer_polite_toggle",):
        order = _target_order(code, layer_order)
        return None if order is None else (R.LAYER_TOGGLE, R.encode_layer_param(order))
    return None   # macros, LED-system, mouse, unknown -> not encoded here (see plan)


def _second_bank_record(rows: list, term: int, flavour: int) -> tuple[int, bytes] | None:
    """A position's double_tap / tap_hold rows -> the secondary-bank hold-tap record.

    The secondary bank reuses the ordinary hold-tap shape: its TAP slot is the key's double-tap
    and its HOLD slot is the key's tap+hold. Either may be absent, in which case that slot is an
    empty keypress -- which is exactly what the device showed for the LED gestures and for keys
    with only one of the two bound.
    """
    dt = next((r for r in rows if _behaviour(r) == "double_tap"), None)
    th = next((r for r in rows if _behaviour(r) == "tap_hold"), None)
    if dt is None and th is None:
        return None
    empty = bytes(4)
    tap_kp = R.encode_keypress(dt["at"], dt["ac"]) if dt is not None else empty
    hold_kp = R.encode_keypress(th["at"], th["ac"]) if th is not None else empty
    return R.HOLD_TAP_ONEKEY, R.encode_holdtap_param(R.HOLD_TAP_ONEKEY, flavour, term, hold_kp, tap_kp)


def _behaviour(row) -> str:
    """Normalise the behaviour name. The UI slot is 'tap+hold' and the device decoder emits
    'tap_hold'; both mean the same slot."""
    b = (row["beh"] or "").replace("+", "_")
    return "tap" if b == "press" else b


def _target_order(code: str, layer_order: dict) -> int | None:
    """'TO_LAYER_<uuid>' / 'TOGGLE_LAYER_<uuid>' / 'MO_LAYER_<uuid>' -> device layer index.

    None if the layer does not exist in this profile. This used to default to 0, which meant a
    stale reference -- to a layer that had been deleted, or copied in from another profile --
    silently flashed as "switch to the base layer". The UI showed it as unresolved while the
    keyboard got a real, wrong binding. An unresolvable switch is not written at all.
    """
    uuid = code.split("_LAYER_", 1)[-1]
    return layer_order.get(uuid)


def _read_term_flavour(conn) -> tuple[int, int]:
    TERM = "8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05"
    FLAV = "24de8555-1a56-4e02-a1c3-3641603a5ac9"
    FLAVOUR_ENUM = {"hold-preferred": 0, "balanced": 1, "tap-preferred": 2, "tap-unless-interrupted": 3}
    term, flavour = 200, 0
    for r in conn.execute("SELECT value, correlation_id FROM settings WHERE correlation_id IN (?,?)", (TERM, FLAV)):
        if r["correlation_id"] == TERM:
            term = int(r["value"])
        else:
            flavour = FLAVOUR_ENUM.get(r["value"], 0)
    return term, flavour


def _read_timeouts(conn) -> tuple[int, int, int] | None:
    IDLE = "ded8e734-b10b-48c9-9ab1-536904e2c3de"
    SLEEP = "f198f968-2c42-4df6-8fdd-97de148cad1a"
    vals = {r["correlation_id"]: r["value"] for r in
            conn.execute("SELECT value, correlation_id FROM settings WHERE correlation_id IN (?,?)", (IDLE, SLEEP))}
    if IDLE not in vals or SLEEP not in vals:
        return None
    return int(vals[IDLE]) * 1000, int(vals[SLEEP]) * 1000, 30000   # sleep_batt default 30s (never captured changing)


def _read_module_safe_fields(conn) -> dict[int, dict[int, tuple[int, bytes]]]:
    """Only the captured-safe module fields (speeds + 1-finger tap). Gesture fields skipped.

    Still empty: the caller supplies module writes explicitly via the module_* helpers below,
    because a slot number is only meaningful next to a live READ_MODULE_CONFIG_LIST (see
    slot_map_for -- slot indices move between flashes)."""
    return {}


# --------------------------------------------------------------------------- #
# module config: slot resolution + targeted writes                            #
# --------------------------------------------------------------------------- #

def slot_map_for(list_payload: bytes) -> dict[str, int]:
    """{module_config_id: slot} from a READ/WRITE_MODULE_CONFIG_LIST payload.

    Slot indices are NOT stable -- Tune was observed moving from slot 4 to slot 2, and Track
    appeared at slot 4 only once its profile was flashed. Always resolve a slot by the module
    config's UUID against a live list read; never hardcode one, or a write lands on another
    module's config.
    """
    return {e["uuid"]: e["slot"] for e in R.parse_module_config_list(list_payload)}


class SlotShapeError(ValueError):
    """A slot's contents do not match the module type we were told to write to."""


def assert_track_shape(fields: dict[int, tuple[int, bytes]]) -> int:
    """Verify a slot really holds a Track config; return the count of trailing junk fields.

    Checked by SHAPE, not field count. Slot 1 on the reference device is a genuine Track Right
    config carrying 21 orphaned Touch fields on the tail (NayaFlow wrote a 15-field Track over a
    36-field Touch and never truncated), so `len(fields) == 15` wrongly refuses a real Track. A
    cleared button field is allowed -- that is the broken state we repair, not a reason to bail.

    Raises SlotShapeError if the slot is not a Track. This is the check that stops a write
    landing on another module's config when the device's own list is mislabelled.
    """
    for f in range(0x00, 0x05):
        if fields.get(f, (None,))[0] != 0x01:
            raise SlotShapeError(f"field {f:#04x} is not a u8 setting")
    motion: dict[int, list[int]] = {}
    for f in range(0x05, 0x0B):
        typ, val = fields.get(f, (None, b""))
        if typ != R.TWO_WORD:
            raise SlotShapeError(f"field {f:#04x} is not a two-word record")
        cat, sel = R.decode_two_word(val)
        if cat == R.MOUSE_CATEGORY or sel not in (1, -1):
            raise SlotShapeError(f"field {f:#04x} is not a motion axis")
        motion.setdefault(cat, []).append(sel)
    if sorted(motion) != [0, 1, 4] or any(sorted(v) != [-1, 1] for v in motion.values()):
        raise SlotShapeError(f"motion axes are not a Track's three pairs: {motion}")
    for f in MF.mouse_button_fields("TRACK").values():
        typ, val = fields.get(f, (None, b""))
        if typ == R.NONE_BEH:
            continue
        if typ != R.TWO_WORD or R.decode_two_word(val)[0] != R.MOUSE_CATEGORY:
            raise SlotShapeError(f"field {f:#04x} is neither a mouse-button record nor cleared")
    return max(0, len(fields) - 15)


def module_button_write(slot: int, module_type: str, changes: dict[str, str]) -> WriteOp | None:
    """Rebind mouse-button gestures (Track buttons, Touch tap-to-click).

    changes: {gesture: 'M1'..'M4'}. Emits a sparse WRITE_MODULE_CONFIG_DATA carrying only the
    changed fields -- the same shape as the 4-byte single-field write NayaFlow was captured
    sending, so the rest of the slot is left alone.
    """
    fields = MF.mouse_button_fields(module_type)
    recs = []
    for gesture, code in sorted(changes.items()):
        if gesture not in fields:
            raise ValueError(f"{module_type} has no mouse-button field for {gesture!r}")
        recs.append(R.encode_module_field(fields[gesture], R.encode_mouse_button(code), R.TWO_WORD))
    if not recs:
        return None
    return WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, recs),
                   f"module {module_type} slot {slot} ({len(recs)} button(s))")


def module_axis_invert(slot: int, module_type: str, current: dict[int, tuple[int, bytes]],
                       category: int) -> WriteOp | None:
    """Flip one motion axis by swapping the +1/-1 selectors of its field pair.

    This is what makes Track rotate scroll the intuitive way: clockwise -> down. Neither
    NayaFlow nor our UI exposes it, but a motion axis is just a (category, direction) pair,
    so inverting it is a two-field sparse write and is reversed by applying it again.
    `current` is the slot as read from the device: {field: (type, value)}.
    """
    pair = MF.motion_axis_fields(module_type).get(category)
    if not pair or len(pair) != 2:
        raise ValueError(f"{module_type} category {category} is not a single axis pair: {pair}")
    recs = []
    for field, other in (pair, pair[::-1]):
        typ, value = current.get(field, (None, None))
        if typ != R.TWO_WORD or value is None:
            raise ValueError(f"field {field:#04x} is not a two-word record on this device")
        cat, _ = R.decode_two_word(value)
        _, other_sel = R.decode_two_word(current[other][1])
        recs.append(R.encode_module_field(field, R.encode_two_word(cat, other_sel), R.TWO_WORD))
    return WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, recs),
                   f"module {module_type} slot {slot} (invert axis category {category})")


# --------------------------------------------------------------------------- #
# plan + frames                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class WriteOp:
    sub: int
    payload: bytes
    label: str
    cat: int = R.CAT_REMAP


# Positions 0x4A-0x51 in layer data are the module dock slots: each holds the module CONFIG
# SLOT bound to that dock (layer 0 on the reference board reads 0x4c -> 4 = Track Left,
# 0x4d -> 1 = Track Right, which is the side-binding proved in C2; higher layers carry 0x78 =
# inherit). The app has no UI for them and desired_from_db does not model them, so a full
# layer write MUST take them from the device rather than defaulting them to NONE -- otherwise
# flashing unassigns every module on the board.
MODULE_SLOT_POSITIONS = range(0x4A, 0x52)


def _full_layer_payload(idx: int, poss: dict[int, tuple[int, bytes]],
                        device: dict[int, tuple[int, bytes]] | None = None) -> bytes:
    """Every position in one layer. Positions absent from `poss` fall back to what the device
    already has (`device`) before defaulting to NONE, so a full write never silently drops
    state the app does not model."""
    device = device or {}
    recs = []
    for pos in ALL_LAYER_POSITIONS:
        if pos in poss:
            typ, param = poss[pos]
        elif pos in MODULE_SLOT_POSITIONS and pos in device:
            typ, param = device[pos]          # carry the module->dock binding through
        else:
            typ, param = device.get(pos, (R.NONE_BEH, b""))
        recs.append(R.record(pos, typ, param))
    return R.encode_layer_data(idx, recs)


def _led_payload(idx: int, leds: dict[int, tuple[int, int]]) -> bytes:
    recs = [R.encode_led_record(i, *leds.get(i, (0, 0))) for i in range(max(leds) + 1 if leds else 0)]
    return R.encode_led_map(idx, recs)


def compute_plan(desired: DesiredState, current: DesiredState | None = None, *, full: bool | None = None) -> list[WriteOp]:
    """Ordered write ops. full=True (or current=None) => rewrite everything; otherwise diff and
    emit only changed layers/leds (sparse per-record diffs are a Phase-C refinement)."""
    full = full if full is not None else current is None
    ops: list[WriteOp] = []
    # --- garbage collection, only when the app actually manages the module set -----------
    # NayaFlow's own removal sequence, captured 2026-09-03: point the bays away first, then
    # delete the list entry, then blank the slot. Doing it in that order means nothing ever
    # references a slot that is being emptied.
    orphans: list[int] = []
    if full and current is not None and desired.module_list is not None:
        orphans = sorted(set(current.modules) - set(desired.module_list))
        if orphans:
            gone = set(orphans)
            for idx, poss in desired.layers.items():
                device_layer = current.layers.get(idx, {})
                for pos in MODULE_SLOT_POSITIONS:
                    slot_now = poss.get(pos, device_layer.get(pos, (None, b"")))[0]
                    if slot_now in gone:
                        # 0 = disabled. Unambiguous on any layer, and it is NayaFlow's own
                        # idiom for a bay with nothing in it.
                        poss[pos] = (0x00, b"")

    for idx in sorted(desired.layers):
        if full or current is None or desired.layers[idx] != current.layers.get(idx):
            ops.append(WriteOp(R.WRITE_LAYER_DATA,
                               _full_layer_payload(idx, desired.layers[idx],
                                                   (current.layers.get(idx) if current else None)),
                               f"layer {idx}"))
    for idx in sorted(desired.leds):
        if desired.leds[idx] and (full or current is None or desired.leds[idx] != current.leds.get(idx)):
            ops.append(WriteOp(R.WRITE_LED_MAP_DATA, _led_payload(idx, desired.leds[idx]), f"led {idx}"))
    for slot in sorted(desired.modules):
        want = desired.modules[slot]
        recs = [R.encode_module_field(f, v, t) for f, (t, v) in sorted(want.items())]
        # Writing N fields does NOT delete fields N+1..M -- that is exactly how the reference
        # board ended up with a 15-field Track config carrying 21 orphaned Touch fields. A full
        # write therefore has to clear what the device has and we do not, explicitly.
        if full and current is not None:
            stale = sorted(set(current.modules.get(slot, {})) - set(want))
            recs += [R.encode_module_field(f, b"", R.NONE_BEH) for f in stale]
        ops.append(WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, recs),
                           f"module slot {slot}"
                           + (f" (+{len(recs) - len(want)} clear(s))" if len(recs) > len(want) else "")))
    if desired.module_list is not None and (full or current is None
                                           or _list_differs(desired, current)):
        entries = [(slot, lid, mtype, uuid)
                   for slot, (lid, mtype, uuid) in sorted(desired.module_list.items())]
        if entries:
            ops.append(WriteOp(R.WRITE_MODULE_CONFIG_LIST, R.encode_module_config_list(entries),
                               f"module list ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'})"))
    for slot in orphans:
        ops.append(WriteOp(R.WRITE_MODULE_CONFIG_LIST, R.encode_module_config_list_delete([slot]),
                           f"drop module list entry {slot}"))
        # Blank the slot LAST and in full: a short write is what leaves a slot holding the
        # previous module's tail (see the Touch/Track hybrid at slot 1).
        ops.append(WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config_blank(slot),
                           f"blank module slot {slot}"))
    if desired.timeouts and (full or current is None or desired.timeouts != current.timeouts):
        ops.append(WriteOp(SYS_SET_TIMEOUTS, R.encode_timeouts(*desired.timeouts), "timeouts", cat=CAT_SYSTEM))
    return ops


def _list_differs(desired: DesiredState, current: DesiredState | None) -> bool:
    """Whether the module list needs rewriting. Without a read we cannot tell, so we do."""
    if current is None or current.module_list is None:
        return True
    return desired.module_list != current.module_list


def render_frames(plan: list[WriteOp], dest: int = 0x50) -> list[tuple[str, list[bytes]]]:
    return [(op.label, R.frames_for(dest, op.sub, op.payload, cat=op.cat)) for op in plan]


def module_gesture_write(slot: int, module_type: str,
                         changes: dict[str, tuple[str, str]]) -> WriteOp | None:
    """Build a sparse WRITE_MODULE_CONFIG_DATA that rebinds gesture key-actions.

    `changes` maps a gesture string to (action_type, action_code), e.g.
    {"tap:tune:2_fingers": ("key", "C_MUTE"), "swipe_up:tune:2_fingers": ("key", "A")}.
    Each gesture is resolved to its device field via module_fields and encoded as a keypress;
    only the changed fields are sent (read-modify-write — the rest of the slot is left as-is).
    Raises if a gesture has no writable keypress field (e.g. an axis/LED gesture, or an
    unmapped module type). Pairs with a prior read so the caller only edits fields it saw."""
    from . import module_fields as mf
    gf = mf.gesture_fields(module_type)
    recs = []
    for gesture, (atype, acode) in sorted(changes.items()):
        field = gf.get(gesture)
        if field is None:
            raise R.RemapEncodeError(
                f"{module_type} gesture {gesture!r} has no writable keypress field "
                f"(axis/LED gesture, or unmapped module)")
        recs.append(R.encode_module_field(field, R.encode_keypress(atype, acode)))
    if not recs:
        return None
    return WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, recs),
                   f"module {module_type} slot {slot} ({len(recs)} gesture(s))")


# --------------------------------------------------------------------------- #
# flash (dry by default)                                                       #
# --------------------------------------------------------------------------- #

def flash(desired: DesiredState, *, transport=None, dest: int = 0x50, current: DesiredState | None = None,
          full: bool | None = None, dry_run: bool = True, reader=None) -> dict:
    """Compute + (optionally) send. dry_run=True (default) sends NOTHING — returns the plan,
    the rendered frames, and a summary. dry_run=False requires a connected transport and is the
    only path that touches the device (ack-checked per frame, then verified via `reader`, a
    callable returning a fresh device read as a DesiredState)."""
    plan = compute_plan(desired, current, full=full)
    rendered = render_frames(plan, dest)
    summary = {
        "dest": f"0x{dest:02x}",
        "ops": [{"label": op.label, "sub": f"0x{op.sub:04x}", "payload_bytes": len(op.payload),
                 "frames": len(frames)} for op, (_, frames) in zip(plan, rendered)],
        "total_frames": sum(len(f) for _, f in rendered),
        "total_bytes": sum(len(op.payload) for op in plan),
    }
    if dry_run:
        return {"dry_run": True, "summary": summary,
                "frames": [f.hex() for _, frames in rendered for f in frames]}

    if transport is None:
        raise ValueError("dry_run=False requires a connected transport")
    return _apply(plan, rendered, transport, desired, reader)


def diff_desired(a: "DesiredState", b: "DesiredState") -> list[dict]:
    """Records/leds in `a` (desired) that differ from `b` (device read-back). Empty = verified.
    Only the positions/leds `a` sets are checked — a full re-read has extra padding we ignore."""
    out = []
    for idx, poss in a.layers.items():
        for pos, rec in poss.items():
            if b.layers.get(idx, {}).get(pos) != rec:
                out.append({"kind": "layer", "layer": idx, "pos": pos,
                            "want": [rec[0], rec[1].hex()],
                            "got": _fmt_rec(b.layers.get(idx, {}).get(pos))})
    for idx, leds in a.leds.items():
        for i, hv in leds.items():
            if b.leds.get(idx, {}).get(i) != hv:
                out.append({"kind": "led", "layer": idx, "led": i,
                            "want": hv, "got": b.leds.get(idx, {}).get(i)})
    return out


def _fmt_rec(rec):
    return None if rec is None else [rec[0], rec[1].hex()]


def _apply(plan, rendered, transport, desired, reader) -> dict:
    """WET write: send each frame, check the ack, then verify by read-back. Aborts on the first
    bad ack (never blind-continues), and reports a verify diff if `reader` is provided. The caller
    is responsible for taking a backup first and restoring on failure."""
    sent = []
    for _op, (label, frames) in zip(plan, rendered):
        for i, frame in enumerate(frames):
            resp = transport._send_raw(frame, 2.0)
            acks = [r for r in resp if getattr(r, "valid", False)]
            flags = acks[0].flags if acks else None
            payload = bytes(acks[0].payload)[:1].hex() if acks and acks[0].payload else None
            sent.append({"op": label, "frame": i, "ack_flags": flags, "ack_payload": payload})
            # A chunked write acks each continuation frame with flags=0x01 and only the last
            # with 0x00 -- confirmed in the captured flash, where every multi-frame layer and
            # LED write does exactly that. Accepting only 0x00 would abort partway through a
            # full layer and leave the keymap half written. The payload byte echoes the layer
            # or slot index (observed live in C1-C4); it is recorded, not gated on.
            if flags not in (0x00, 0x01):
                return {"status": "aborted", "op": label, "frame": i, "ack_flags": flags,
                        "sent": sent, "reason": "bad or missing ack — not continuing"}
    result = {"status": "sent", "ops": len(plan), "frames": len(sent), "sent": sent}
    if reader is not None:
        readback = reader()                       # a fresh device read as a DesiredState
        mism = diff_desired(desired, readback)
        result["verify"] = mism
        result["status"] = "verified" if not mism else "verify-failed"
    else:
        result["status"] = "sent-unverified"
    return result


# --------------------------------------------------------------------------- #
# per-layer module bays -> slots, list entries and configs                     #
# --------------------------------------------------------------------------- #

def apply_module_layout(desired: DesiredState, conn, mod_read: dict) -> dict:
    """Fold the app's per-layer module choices into a DesiredState.

    Until now the app could never CHANGE a bay by flashing: desired_from_db did not model them
    and _full_layer_payload carried the device's own bay bytes through, specifically so a flash
    would not unassign every module. This is what makes the app the author instead.

    Three coordinated writes come out of it, exactly as captured from NayaFlow:
    the bay byte per layer, the module-config list entry, and the config itself. compute_plan
    already knows how to emit all three -- this only has to fill them in.

    Only NEWLY ALLOCATED slots get a config write. A profile the board already carries is left
    alone, which is why re-flashing an unchanged layout sends no module data at all.

    Returns the layout plan for reporting. Mutates `desired`.
    """
    from . import module_fields, module_layout as ml

    pid = desired.profile_id
    order_of = {r["id"]: r["order_id"] for r in
                conn.execute("SELECT id, order_id FROM layers WHERE profile_id = ?", (pid,))}
    bays_by_layer: dict[int, dict[str, str]] = {o: {} for o in order_of.values()}
    for r in conn.execute(
            "SELECT layer_id, module_config_id, binding_location, state "
            "FROM module_config_bindings WHERE profile_id = ?", (pid,)):
        order = order_of.get(r["layer_id"])
        if order is None:
            continue
        bays_by_layer[order][r["binding_location"]] = r["state"] or r["module_config_id"]

    types, captured_from = {}, {}
    for r in conn.execute("SELECT id, type, captured_from FROM module_configs"):
        types[r["id"]] = r["type"]
        if r["captured_from"]:
            captured_from[r["id"]] = r["captured_from"]
    # Single-field gestures and axis gestures are read apart, because an axis is TWO fields and
    # its two halves can be bound independently once the gesture is split.
    bindings: dict[str, dict[str, str]] = {}
    axes: dict[str, dict[str, dict]] = {}
    for r in conn.execute(
            "SELECT module_config_id, behavior, action_code, direction, invert "
            "FROM module_bindings"):
        cid, beh = r["module_config_id"], r["behavior"]
        typ = types.get(cid)
        if typ and beh in module_fields.axis_halves(typ):
            spec = axes.setdefault(cid, {}).setdefault(beh, {"minus": None, "plus": None,
                                                             "invert": False})
            if r["invert"]:
                spec["invert"] = True
            # The stock form is ONE row holding both halves as "mouse - LEFT - RIGHT"; that is
            # not a per-half binding, so it leaves the axis records in place. A split stores a
            # row per half, keyed by the direction column.
            code = r["action_code"] or ""
            if code and " - " not in code:
                spec["plus" if (r["direction"] or "+") == "+" else "minus"] = code
        else:
            bindings.setdefault(cid, {})[beh] = r["action_code"]

    # The Tune dial is a PAIR: two fields, and the app may hold it as one combined row
    # ("C_VOL_DOWN - C_VOL_UP") rather than as the two half gestures. Without expanding that,
    # the stock Tune profile wrote nothing to either dial field -- the halves looked empty and
    # the combined row matched no writable field, so the dial silently never flashed.
    for cid, rows in bindings.items():
        for combined, halves in module_fields.paired_gestures(types.get(cid) or "").items():
            minus, plus = module_fields.split_pair(rows.get(combined))
            for sign, code in (("-", minus), ("+", plus)):
                half = halves[sign]
                if code and not rows.get(half):   # an explicit half wins over the pair
                    rows[half] = code

    # Module settings -- speeds, acceleration, tick feedback. Stored per config by schema id.
    settings: dict[str, dict] = {}
    for r in conn.execute("SELECT module_config_id, correlation_id, value FROM module_settings"):
        settings.setdefault(r["module_config_id"], {})[r["correlation_id"]] = r["value"]

    device_list = [{"slot": slot, "uuid": uuid}
                   for uuid, slot in (mod_read.get("by_uuid") or {}).items()]
    device_slots = {}
    for slot, fields in (mod_read.get("slots") or {}).items():
        device_slots[int(slot)] = {int(f["field"]): (f["type"], bytes.fromhex(f["value"]))
                                   for f in fields}

    base_order = min(order_of.values()) if order_of else 0
    layout = ml.plan(bays_by_layer, types, device_list, device_slots, base_order=base_order,
                     captured_from=captured_from)

    # The bay byte lives in the record's TYPE field with an empty param -- 014c0500 is
    # layer 1, position 0x4c, type 05 (slot 5), length 0.
    for order, row in layout["bays"].items():
        if order not in desired.layers:
            continue
        for pos, value in row.items():
            desired.layers[order][pos] = (value, b"")

    desired.module_list = {slot: (lid, code, uuid16)
                           for slot, lid, code, uuid16 in layout["list_entries"]}
    for cid in layout["allocated"] + layout["claimed"] + layout["kept"]:
        if cid not in layout["templates"]:
            continue                      # slot contents unreadable: leave it alone
        slot = layout["slot_for"][cid]
        cfg = ml.overlay(layout["templates"][cid], types[cid], bindings.get(cid, {}),
                         axes.get(cid, {}), settings.get(cid, {}))
        # Anything templated from its OWN slot and coming out identical needs no data write --
        # sending the same bytes back would be churn on every flash. A difference means the app
        # and the board genuinely disagree, and the flash is what resolves that.
        if cid not in layout["allocated"] and cfg == layout["templates"][cid]:
            continue
        desired.modules[slot] = cfg
    return layout


def module_field_write(slot: int, field: int, type_byte: int, value: bytes) -> WriteOp:
    """Write ONE module-config field, whatever record type it holds.

    module_gesture_write only emits keypresses and module_button_write only mouse masks, so
    neither can put an arbitrary record in a named field -- which is the one thing needed to test
    what a field ACCEPTS. A gesture field is not type-locked: the same index holds a keypress or
    a two-word record depending on the type byte, proved by a Track profile whose buttons were
    bound to letters where stock holds mouse masks.

    Sparse: only this field is sent, so the rest of the slot is left exactly as it was. The
    caller is responsible for having read the slot first and for being able to put it back.
    """
    if not 0 <= field <= 0xFF:
        raise ValueError(f"field out of range: {field}")
    if len(value) > 0xFF:
        raise ValueError(f"value too long for one record: {len(value)} bytes")
    rec = R.encode_module_field(field, value, type_byte)
    return WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, [rec]),
                   f"module slot {slot} field 0x{field:02x} "
                   f"(type 0x{type_byte:02x}, {len(value)} byte(s))")
