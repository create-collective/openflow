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
  -> WRITE_LAYER_LIST again, the FULL table, always (restores lighting -- see
     _lighting_restore_ops; measured 2026-09-10)
  -> verification reads + diff

Everything here is dry unless `flash(..., dry_run=False)` is called with a live transport.
Module GESTURE bindings are intentionally NOT written — see MODULE CONFIDENCE below.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .._vendor.nayactl.constants import CAT_SYSTEM
from . import keymap_read
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
# The app models 97 key positions; the board reports 136 LEDs per layer. The 39 past the key
# range are the RIGHT module's block, and they are not individually addressable colours -- all 39
# carry ONE value, confirmed identical within each layer in every capture we hold.
#
# That value tracks key position 88. Derived by diffing NayaFlow's own database against the map
# it produced on the board: LEDs 82-89 map identity to positions 82-89, and the 97-135 block
# always equals what positions 88/89 hold. 88 and 89 carry the same colour in both profiles we
# have, so which of the two is the real source is NOT yet distinguished -- it needs a profile
# where they differ. Either way this reproduces the vendor's behaviour on everything we can check.
#
# INFERRED, from one NayaFlow flash. To falsify: colour positions 88 and 89 differently, flash,
# and see which one the right-hand module follows.
KEY_POSITIONS = 97
# The LED blocks that light the docked modules, measured 2026-09-08 by painting each band a
# distinct colour and looking at the keyboard:
#
#     74-80 / 81-87   the two side edges, 7 each (layout.js RIGHT_LEDS / LEFT_LEDS)
#     88-111          LEFT bay    24
#     112-135         RIGHT bay   24
#
# EACH BAY GETS 24 LEDS AND THE MODULE LIGHTS AS MANY AS IT HAS. A Tune has 9 and a Track 15, so
# with a Tune on the left only 88-96 lit and 97-111 looked dead; with a Track on the right only
# 112-126 lit and 127-135 looked dead. That is one block each, not four, and it is symmetric --
# 24 and 24.
#
# It is keyed to the BAY, not the module: swapping the Tune and Track kept each side's colour,
# so the left bay stayed green and the right red while the hardware in them changed places. An
# earlier reading here had a 9-block and a 15-block per side, one per module TYPE; the swap
# disproved it. Painting the whole 24 is therefore correct whatever is docked.
#
# The left block starts inside the key range (88-96), which is why key colours were already
# reaching the left module while the right -- with no key position at all -- kept whatever the
# last application wrote.
# A bay reserves a block sized for the LARGEST module type, and whatever is docked lights as many
# LEDs as it has. A Tune is a ring (~9, seen at 88-96); a Track and a Touch are a single dot, so
# they light through ONE index of their block. Painting the whole block is therefore correct
# whatever is docked, and harmless for the indices nothing is wired to.
#
# The exact boundary between the two blocks is still inferred rather than measured -- 97-111 lit
# nothing with a Tune on the left, which is equally consistent with the tail of the left block or
# the head of the right. It does not matter while we paint each block a single colour. It would
# matter if per-LED module colour ever became a feature.
MODULE_LED_BLOCKS = {"left": range(88, 112), "right": range(112, 136)}
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
    # idx -> LED animation index (0 solid / 1 breathe / 2 spectrum / 3 swirl -- ZMK's order, see
    # keymap_read.LAYER_ANIMATIONS). Byte 2 of the layer-list entry. Hardcoded 0 here until
    # 2026-09-08, which reset every layer to solid.
    layer_animations: dict[int, int] = field(default_factory=dict)
    # idx -> {"left"/"right": "#rrggbb"} for the docked modules' LED blocks. The right module has
    # no key position at all, so without this a flash left it on whatever wrote it last.
    module_leds: dict[int, dict[str, str]] = field(default_factory=dict)
    profile_id: str | None = None                                                     # which profile this came from
    # {slot: (list_id, module_type, uuid16)} -- the module-config LIST the app intends.
    # None means the app is not managing the module set, and NOTHING is garbage collected.
    # That distinction matters: desired.modules is empty today, so a naive "anything on the
    # device we do not want is an orphan" rule would wipe every module config on the board.
    module_list: dict[int, tuple[int, int, bytes]] | None = None
    # Bindings the user set that could NOT be encoded. This exists because
    # _binding_rows_to_record returning None was completely silent: the position was simply
    # never added, _full_layer_payload then fell back to whatever the device already had, and
    # the flash reported "verified" because verification only checks records the plan SET.
    # So a key set to Disabled kept its old binding and nothing said so.
    dropped: list[dict] = field(default_factory=list)
    # {layer: {pos + 0x52}}: second-bank slots whose double-tap / tap+hold could not be encoded.
    # _own_second_bank must leave these to the board. Blanking them is how a double-tap NayaFlow
    # wrote, which read back as RAW, used to vanish on the next OpenFlow flash with no report.
    keep_second_bank: dict[int, set[int]] = field(default_factory=dict)


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


# The LED record is [led][hue u16][SATURATION]. Not brightness -- see keymap_read.hsv_to_hex for
# the evidence. Writing brightness here is what turned every white key RED on the keyboard.
_hex_to_hue_sat = keymap_read.hex_to_hue_sat


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
    for idx, anim in (read.get("layer_animations") or {}).items():
        d.layer_animations[int(idx)] = int(anim)
    for idx, uuid_str in (read.get("layer_uuids") or {}).items():
        try:
            d.layer_uuids[int(idx)] = R.layer_uuid_bytes(uuid_str)
        except ValueError:
            pass          # a board with an unreadable id is a reason to REWRITE it, not to fail
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
    # animation_id is queried defensively: older databases and the test fixtures predate the
    # column, and a missing LED animation is not a reason to refuse to flash a keymap.
    _cols = {r[1] for r in conn.execute("PRAGMA table_info(layers)")}
    _anim_sel = ", animation_id" if "animation_id" in _cols else ""
    _mod_sel = (", module_led_left, module_led_right"
                if {"module_led_left", "module_led_right"} <= _cols else "")
    for lrow in conn.execute(
            f"SELECT id, order_id{_anim_sel}{_mod_sel} FROM layers WHERE profile_id = ? "
            f"ORDER BY order_id",
            (pid,)):
        idx = lrow["order_id"]
        d.layers[idx], d.leds[idx] = {}, {}
        # The identity table the board should end up with. Without this the device keeps whatever
        # UUIDs were last written to it -- by NayaFlow, in practice -- and a later read matches
        # our layers against those, attributing bindings to the wrong layers entirely.
        try:
            d.layer_uuids[idx] = R.layer_uuid_bytes(lrow["id"])
        except ValueError:
            pass      # not a uuid (fixtures use short ids); the completeness guard below drops it
        d.layer_animations[idx] = keymap_read.LAYER_ANIMATION_IDS.get(
            ((lrow["animation_id"] if _anim_sel else None) or "solid"), 0)
        if _mod_sel:
            d.module_leds[idx] = {k: v for k, v in
                                  (("left", lrow["module_led_left"]),
                                   ("right", lrow["module_led_right"])) if v}
        q = conn.execute(
            "SELECT k.position_id p, k.color_hex, b.action_type at, b.action_code ac, b.behavior beh "
            "FROM keys k LEFT JOIN key_bindings b ON b.key_id = k.id WHERE k.layer_id = ? ORDER BY k.position_id",
            (lrow["id"],))
        # group multiple binding rows per position (tap+hold)
        by_pos: dict[int, list] = {}
        colors: dict[int, str] = {}
        for r in q:
            if r["p"] is None:
                continue
            # LED positions and BINDING positions are different domains, and conflating them
            # discarded colour. Layer records stop at 0x51 (FULL_LAYER_POSITIONS), but the LED
            # map is its own thing -- the DB models 97 key positions and the board reports 136
            # LEDs per layer. Gating colour on the binding range silently dropped positions
            # 82-96, so a flash wrote LEDs 0-81 and left the rest holding whatever was there
            # before. Reported as "the module LEDs stayed green rather than purple".
            #
            # But not past 87. Positions 88-96 exist in the app's 97-position model and sit
            # INSIDE the left module bay block (88-111), which is painted as one colour from
            # `module_led_left` or, when that is unset, carried through from the board. A key
            # row's colour there is a leftover from an old import and must never reach the
            # wire: it is what would have striped the left bay purple and orange over green
            # (planned against the 2026-09-09 read). NayaFlow's own flash behaves the same
            # way -- its stored values at 90-96 never appear on the board as colours.
            if r["color_hex"] and r["p"] <= keymap_read.LAST_KEYED_LED:
                colors[r["p"]] = r["color_hex"]
            if r["at"] is not None and r["p"] in FULL_LAYER_POSITIONS:
                by_pos.setdefault(r["p"], []).append(r)
        for pos, rows in by_pos.items():
            # One unencodable binding must cost that key, not the flash. Before this, a
            # single hold slot the board carried as zeros aborted the preview and no key
            # on the board could be written (SCRUM-95).
            try:
                rec = _binding_rows_to_record(rows, term, flavour, layer_order)
            except R.RemapEncodeError:
                rec = None
            if rec is not None:
                d.layers[idx][pos] = rec
            else:
                # NOT written as NONE. Clearing the key would destroy a binding the user never
                # asked to remove; leaving it and SAYING so is the honest option. The report
                # states what the key will actually keep doing.
                culprit = _failing_row(rows, term, flavour, layer_order)
                d.dropped.append({
                    "layer": idx, "position": pos,
                    "actionCode": culprit["ac"], "actionType": culprit["at"],
                    "behavior": culprit["beh"],
                    "reason": _drop_reason(culprit["at"], culprit["ac"], culprit.get("error")),
                    "effect": "this key keeps whatever the keyboard already had on it",
                })
            # double-tap / tap+hold are a second hold-tap record at pos + 0x52
            try:
                second = _second_bank_record(rows, term, flavour)
            except R.RemapEncodeError as e:
                second = None
                culprit = next(r for r in rows if _behaviour(r) in ("double_tap", "tap_hold")
                               and not _encodes_as_keypress(r))
                d.dropped.append({
                    "layer": idx, "position": pos,
                    "actionCode": culprit["ac"], "actionType": culprit["at"],
                    "behavior": _behaviour(culprit),
                    "reason": _drop_reason(culprit["at"], culprit["ac"], str(e)),
                    "effect": "this key keeps whatever double-tap and tap+hold the keyboard "
                              "already had",
                })
                d.keep_second_bank.setdefault(idx, set()).add(pos + SECOND_BANK)
            if second is not None:
                d.layers[idx][pos + SECOND_BANK] = second
        for pos, hexc in colors.items():
            if len(hexc) == 7 and hexc[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in hexc[1:]):
                d.leds[idx][pos] = _hex_to_hue_sat(hexc)
    d.timeouts = _read_timeouts(conn)
    d.modules = _read_module_safe_fields(conn)
    return d


# --- DB -> record helpers (semantic; the interesting mapping) --------------- #

# Why a binding could not be encoded, in words a user can act on. Keyed by actionType, because
# that is what decides the record -- not the code. Anything unlisted still reports, with the
# type named, rather than falling through to silence.
_DROP_REASONS = {
    "none": "Disabled cannot be written yet.",
    "trans": "Transparent cannot be written yet.",
    "out": "Only Wireless (BT_OUT) and USB-C (USB_DEVICE) have a known output record.",
    "LED": "Not one of the LED actions NayaCore defines (its 19 are all written).",
    "macro": "The keyboard reserves a macro type but implements no macro table, so a macro "
             "binding can never reach it.",
    "bluetooth": "Only Bluetooth devices 1-4, Clear, Next and Previous have a known record.",
}


# Layer switches DO have encoders. When one of these is dropped it is never the type that is
# unsupported -- it is the layer it points AT that could not be resolved.
_LAYER_TYPES_WITH_ENCODERS = ("layer_polite_hold", "layer_rude_toggle", "layer_polite_toggle")


def _keypress(action_type: str | None, code: str | None) -> bytes:
    """The 4-byte keypress for one binding slot.

    EMPTY_KEYPRESS is the DECODER'S NAME for an all-zero keypress record -- a key that
    presses nothing, which the board really does carry (a hold-tap whose hold slot is
    unset, and the Tune gestures NayaFlow labels LED Brightness). Reading one and then
    refusing to write it back is not a safety property, it is a failed round trip: the
    bytes are known exactly, because the name is ours and means those bytes.

    Without this a single such key aborted the whole flash preview before anything was
    sent, so nothing else on the board could be flashed either (SCRUM-95).
    """
    if code == R.EMPTY_KEYPRESS:
        return bytes(4)
    return R.encode_keypress(action_type, code)


def _failing_row(rows: list, term: int, flavour: int, layer_order: dict) -> dict:
    """Which of a key's rows could not be encoded.

    The drop report used to name the PRESS row regardless, so a key whose tap encoded fine and
    whose hold did not was reported as "no encoder for action type 'key'" -- pointing the user
    at the one binding that was not the problem (SCRUM-110: RETURN / BACKSPACE with a layer-tap
    hold the decoder had not named). Re-trying the press alone tells the two cases apart; if the
    press itself fails, it is rightly the one reported.
    """
    press = next((r for r in rows if r["beh"] in ("press", "tap", None)), rows[0])
    others = [r for r in rows if r is not press]

    def attempt(subset):
        """(ok, error text). The encoder's own words are the reason a user can act on --
        "unknown base key 'V\\xa0'" says what "no encoder for action type" never could."""
        try:
            return _binding_rows_to_record(subset, term, flavour, layer_order) is not None, None
        except R.RemapEncodeError as e:
            return False, str(e)

    ok, err = attempt([press])
    if not ok or not others:
        return {**press, "error": err}
    for r in others:
        ok, err = attempt([press, r])
        if not ok:
            return {**r, "error": err}
    return {**press, "error": None}


def _drop_reason(action_type: str | None, code: str | None, error: str | None = None) -> str:
    if (code or "").startswith("RAW_"):
        # The decoder could not name what the board holds here. EMPTY_KEYPRESS is handled
        # (see _keypress); anything else RAW_ is bytes we have never seen.
        return ("The keyboard holds a record here that OpenFlow cannot name yet, so it "
                "cannot be written back.")
    if error:
        # The encoder refused this binding and said why. Its words are the reason -- "unknown
        # base key 'V\xa0' in 'LCTRL\xa0+\xa0LSHIFT\xa0+\xa0V'" names a stray character the eye
        # cannot see, where "no encoder for action type 'shortcut_alias'" sent a tester (and
        # us) looking at a type that encodes perfectly well (2026-09-22).
        return f"OpenFlow could not encode this binding: {error}."
    base = _DROP_REASONS.get(action_type or "")
    if base:
        return base
    if action_type in _LAYER_TYPES_WITH_ENCODERS:
        # Saying "no encoder for 'layer_polite_hold'" here was simply WRONG, and it sent the
        # device owner looking for a missing feature instead of a broken reference. `MO_LAYER_-1`
        # is the shape it takes: the importer wrote -1 where a layer UUID belongs, because it was
        # decoding a module bay as a binding (see keymap_read.BAY_POSITIONS). A stale reference
        # to a deleted or copied-in layer produces the same drop.
        target = (code or "").split("_LAYER_", 1)[-1]
        if target in ("-1", ""):
            return ("This points at layer -1, which is not a real layer. It comes from an old "
                    "read that mistook a module bay for a key; deleting this binding is safe.")
        return (f"The layer this points at ({target}) is not in this profile, so there is no "
                f"index to write. It was probably deleted or copied in from another profile.")
    return f"OpenFlow has no encoder for action type {action_type!r} yet."


def _binding_rows_to_record(rows: list, term: int, flavour: int, layer_order: dict) -> tuple[int, bytes] | None:
    """One position's binding row(s) -> (type, param). Handles key/modifier/shortcut, layer
    switches, bluetooth, and tap+hold (a 'press' row + a 'hold' row)."""
    press = next((r for r in rows if r["beh"] in ("press", "tap", None)), rows[0])
    hold = next((r for r in rows if r["beh"] == "hold"), None)
    at, code = press["at"], press["ac"]
    # Double-tap and tap+hold live in the SECOND bank, but they only ever fire if the primary
    # record is a hold-tap: that record is what runs the tapping-term state machine that can
    # notice a second tap. A plain KEY_PRESS fires the instant it is pressed and the second bank
    # is never consulted. Measured 2026-09-21 (SCRUM-109): Tap A + Double-tap B with Hold empty
    # produced "aa" on a double tap and never "b"; filling Hold with anything "fixed" it, because
    # that flipped the primary to a hold-tap. So a key with either second-bank behaviour gets a
    # hold-tap primary even with no hold action -- with the hold slot EMPTY (four zero bytes),
    # which is the device's own convention for an unset half (SCRUM-96) and reads back as no
    # hold. A tap-only key stays a plain keypress: promoting it would add tapping-term latency
    # to a key that has nothing to wait for.
    second_bank = any(_behaviour(r) in ("double_tap", "tap_hold") for r in rows)
    can_be_tap = at in ("key", "modifier", *R.CHORD_ACTION_TYPES) or code == R.EMPTY_KEYPRESS

    if hold is not None or (second_bank and can_be_tap):
        tap_kp = _keypress(at, code)
        if hold is not None and hold["at"] == "layer_polite_hold":
            # A layer in the hold slot: ZMK's layer-tap, which a stock board carries on its
            # Enter and Backspace keys (hold for layer 2). The slot holds the layer INDEX and the
            # header's hold-kind byte says so (SCRUM-110). Written as the 0x03 form, because
            # that is byte for byte what the board holds for these keys -- a profile read from a
            # stock board and flashed back must not rewrite them -- and the 0x10 form with a
            # layer hold has never been seen on hardware.
            order = _target_order(hold["ac"], layer_order)
            if order is None:
                raise R.RemapEncodeError(f"hold layer {hold['ac']!r} is not in this profile")
            return R.HOLD_TAP_HOME, R.encode_holdtap_param(
                R.HOLD_TAP_HOME, flavour, term, R.encode_layer_param(order), tap_kp,
                hold_kind=R.LAYER_HOLD)
        # The record TYPE changes how the key types, not just what it is called. 0x10 (OneKey)
        # is the four-behaviour record: its tap waits for a possible double-tap, so it lands on
        # release or after the tapping term, and a key pressed meanwhile goes out first. On a
        # home-row mod that swaps letters ("few" -> "efw") and drops some. 0x03 (MOD_TAP) sends
        # the tap in order. Measured 2026-09-25 (tools/c11_homerow_timing.py): D/F/J/K as
        # hold-mod/tap-letter, same flavour and term, 0x10 garbled 5 fast sentences of 5 and 0x03
        # typed them clean. NayaFlow draws the line in the same place: in its captured flash
        # (tests/hold-tap-fixture.json) every tap+hold key is 0x03 except the one that also has a
        # second-bank record. So 0x10 only when the second bank is in play.
        hold_kp = _keypress(hold["at"], hold["ac"]) if hold is not None else bytes(4)
        typ = R.HOLD_TAP_ONEKEY if second_bank else R.HOLD_TAP_HOME
        return typ, R.encode_holdtap_param(typ, flavour, term, hold_kp, tap_kp)

    if at in ("key", "modifier", *R.CHORD_ACTION_TYPES):
        return R.KEY_PRESS, _keypress(at, code)
    if at == "none":
        # DISABLE -> the NONE record, empty param. Better evidenced than anything else here:
        # ~220 of these come back in every board read, and NayaCore has been captured writing
        # them three separate ways (blanking whole layers in flash3, a sparse `49 07 00` edit,
        # and the `2e 07 00` from the macro investigation). flash.py already emits this exact
        # record for unmodelled positions -- the only thing missing was a user reaching it.
        #
        # Until this existed, setting a key to Disabled left the key doing whatever it did
        # before, because the position fell through to the device's own record.
        return R.NONE_BEH, b""
    if at == "trans":
        # TRANSPARENT -> 0x0e, empty param. 23-25 per board read, and captured from NayaCore in
        # both full-layer (flash2) and sparse form. Encoding it also closes a real hole in
        # mode="recovery", which has no device read to fall back on and so turned every TRANS on
        # the board into NONE.
        return R.TRANS, b""
    if at == "mouse":
        # A key takes the SAME two-word record a module gesture does: [cat 3][button mask].
        # Measured, not assumed -- writing 0f 08 03000000 01000000 to a key position and
        # pressing it produces a real left click (tools/c9_key_record_probe.py, mouse-twoword).
        # The ZMK shape (a bare mask) was the other candidate and is not what this firmware wants.
        try:
            return R.TWO_WORD, R.encode_mouse_button(code)
        except R.RemapEncodeError:
            return None
    if at == "LED":
        # The LED system keys (&rgb_ug). Decoded from the board since 2026-09-08 and now
        # encodable, so reading a profile off the keyboard and flashing it back keeps them
        # instead of quietly dropping fourteen keys.
        try:
            return R.RGB_SYS, R.encode_rgb_system(code)
        except R.RemapEncodeError:
            return None
    if at == "out":
        # Wireless / USB-C output switching, the 0x08 record. Held back until 2026-09-09 "pending
        # a hardware check" -- but the check that matters for WRITING is already in hand: these
        # are the bytes NayaFlow itself put on this board (layer 2, positions 0x2f/0x30/0x47/0x48),
        # and the name-to-selector mapping comes from NayaFlow's database at those positions.
        # What a keypress would still settle is only what the firmware does on the press, which
        # changes no byte here. Refusing to write them stranded every Bluetooth-output key.
        sel = R.OUTPUT_SELECTOR_REV.get(code)
        return None if sel is None else (R.OUTPUTS, R.encode_layer_param(sel))
    if at == "bluetooth":
        if code == "BT_CLEAR":
            return R.TWO_PARAM, R.encode_twoparam(R.BT_CLEAR_CMD, 0)
        for cmd, name in keymap_read.BT_STEP.items():
            if code == name:                   # next / previous device, from NayaCore's table
                return R.TWO_PARAM, R.encode_twoparam(cmd, 0)
        prof = R.BT_PROFILE_REV.get(code)
        if prof is not None:
            return R.TWO_PARAM, R.encode_twoparam(R.BT_SELECT, prof)
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
    if at in ("layer_polite_oneshot",):
        # Sticky Layer. Refused until 2026-09-08 because the type had never been seen on a
        # device; a probe proved it real, param = target layer, same shape as the others.
        order = _target_order(code, layer_order)
        return None if order is None else (R.STICKY_LAYER, R.encode_layer_param(order))
    if at == "naya":
        cmd = R.NAYA_COMMANDS_REV.get(code)
        return None if cmd is None else (R.NAYA_SYSTEM, R.encode_layer_param(cmd))
    return None   # macros, LED-system, unknown -> not encoded here (see plan)


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
    tap_kp = _keypress(dt["at"], dt["ac"]) if dt is not None else empty
    hold_kp = _keypress(th["at"], th["ac"]) if th is not None else empty
    return R.HOLD_TAP_ONEKEY, R.encode_holdtap_param(R.HOLD_TAP_ONEKEY, flavour, term, hold_kp, tap_kp)


def _encodes_as_keypress(row) -> bool:
    try:
        _keypress(row["at"], row["ac"])
        return True
    except R.RemapEncodeError:
        return False


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
    # No saved flavour means what the settings page shows as its default: Balanced (1).
    # NayaFlow also displays "Balanced" by default but sends 0, which is hold-preferred. Measured
    # 2026-09-25 with home-row mods: at 0, any key pressed during a home-row key turned it into
    # the modifier on fast rolls (select-all, new tabs); at 1 the same typing came out clean.
    term, flavour = 200, FLAVOUR_ENUM["balanced"]
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


def _own_second_bank(poss: dict[int, tuple[int, bytes]],
                     keep: set[int] | frozenset[int] = frozenset()) -> dict[int, tuple[int, bytes]]:
    """The second-bank NONE records a profile owes for the keys it sets.

    A key's double-tap and tap+hold live at position + 0x52. When the profile sets a key and
    gives it no double-tap / tap+hold, that slot is EMPTY -- and empty has to be WRITTEN, not
    left to whatever the board holds. Until 2026-09-09 it was left: _full_layer_payload carried
    the device's record through for every position the profile did not mention, and that
    included the shadows of keys the profile very much did mention.

    What that did on real hardware: keys 53 and 73 had four behaviours under an old profile; the
    profile was later reduced to tap-only, and both apps kept re-flashing the board with the two
    stale shadows intact. NayaFlow could not remove them either (its sparse diff only covers
    records its profile holds), and its verify then read them back against '(empty)' and failed
    every flash -- "Failed to verify written data", with the primaries reported as four-behaviour
    keys because a shadow existed. docs/nayaflow-verify-test-plan.md has NayaCore's log and the
    hardware run that confirmed it.

    Only KEYS the profile sets are affected. A position the profile does not mention keeps both
    its banks from the device, as before: the profile has no opinion about that key, so it must
    not have one about its double-tap either. Bays have no second bank.

    `keep` is the shadows whose double-tap / tap+hold the profile HAS but could not encode
    (DesiredState.keep_second_bank). The profile does have an opinion there, one we cannot write,
    so the board's record stays and the flash report says so.
    """
    return {pos + SECOND_BANK: (R.NONE_BEH, b"")
            for pos in poss
            if pos in SECOND_BANK_KEYS and pos + SECOND_BANK not in poss
            and pos + SECOND_BANK not in keep}


def _layer_needs_write(desired_layer: dict[int, tuple[int, bytes]],
                       current_layer: dict[int, tuple[int, bytes]]) -> bool:
    """Does any position the profile sets differ from what the board holds?

    Compared per position, not as whole dicts: a profile models a subset of the 156 positions
    and a device read returns all of them, so whole-dict equality was never true on a real sync
    flash and every layer was rewritten every time. A position missing from `current_layer`
    counts as NONE -- the device pads every unbound position with `07 00`, so on the wire
    'absent' and 'empty' are the same record.
    """
    empty = (R.NONE_BEH, b"")
    return any(current_layer.get(pos, empty) != rec for pos, rec in desired_layer.items())


def _module_led_values(colours: dict[str, str] | None) -> dict[int, tuple[int, int]]:
    """{"left": "#rrggbb"} -> {led index: (hue, saturation)} across that module's block."""
    out: dict[int, tuple[int, int]] = {}
    for side, hexc in (colours or {}).items():
        block = MODULE_LED_BLOCKS.get(side)
        if not block or not hexc:
            continue
        value = keymap_read.hex_to_hue_sat(hexc)
        for i in block:
            out[i] = value
    return out


def _led_payload(idx: int, leds: dict[int, tuple[int, int]],
                 device: dict[int, tuple[int, int]] | None = None,
                 module_colours: dict[str, str] | None = None) -> bytes:
    """One layer's LED map.

    `device` is what the board currently holds for this layer. It matters because the board has
    MORE LEDs than the app models -- 136 per layer against the DB's 97 key positions. Stopping at
    the profile's highest coloured position left the remainder showing whatever the last app to
    write them chose, which is how module LEDs stayed on NayaFlow's green through an OpenFlow
    flash.

    So the write now spans the whole map the device reports, and the LEDs we have no model for
    are passed through UNCHANGED rather than invented. Writing a default into them would replace
    one wrong colour with another and destroy whatever the modules are meant to show.
    """
    device = device or {}
    module_leds = _module_led_values(module_colours)
    # (0, 0) is WHITE now that the third byte is saturation, so an LED the profile does not
    # mention must carry the unset sentinel rather than a colour.
    unset = (0, keymap_read.UNSET_SATURATION)
    count = max([*leds, *device, *module_leds], default=-1) + 1
    recs = []
    for i in range(count):
        if i in module_leds:
            value = module_leds[i]          # an explicit module colour wins over everything
        elif i in leds:
            value = leds[i]
        else:
            # No model for this LED: keep what the device has rather than invent a colour.
            # Writing a default into the module blocks would wipe whatever they should show.
            value = device.get(i, unset)
        recs.append(R.encode_led_record(i, *value))
    return R.encode_led_map(idx, recs)


def _blank_layer_payload(idx: int) -> bytes:
    """A deleted layer's data, wiped. `07 00` (none) everywhere, `00 00` on the module bays.

    The firmware does NOT clear a deleted layer's data or LED map on its own -- NayaCore sends
    both explicitly (docs/write-protocol-spec.md:14). Leaving them would strand records on an
    index a later layer could be created at."""
    recs = [R.record(pos, 0x00 if pos in MODULE_SLOT_POSITIONS else R.NONE_BEH, b"")
            for pos in ALL_LAYER_POSITIONS]
    return R.encode_layer_data(idx, recs)


def _layer_list_ops(desired: DesiredState, current: DesiredState | None) -> list[WriteOp]:
    """WRITE_LAYER_LIST for added / re-identified / removed layers, plus the wipes a delete needs.

    Returns [] when the board already agrees, which is the common case: this must not fire on an
    ordinary flash. Both payload forms come from captured NayaCore flashes -- see remap.py.
    """
    # Every layer or none. A PARTIAL identity table is worse than no write at all: it would
    # name some indexes correctly and leave others pointing at whatever was there before, which
    # is the exact failure this whole change exists to fix.
    if not desired.layer_uuids or set(desired.layer_uuids) != set(desired.layers):
        return []
    have = dict(current.layer_uuids) if current else {}
    ops: list[WriteOp] = []

    # Added, or sitting at an index that names a different layer (the stale-identity case).
    have_anim = dict(current.layer_animations) if current else {}
    changed = [(i, u, desired.layer_animations.get(i, 0))
               for i, u in sorted(desired.layer_uuids.items())
               # A DIFFERENT ANIMATION is a reason to rewrite the entry too, not just a different
               # uuid -- it lives in the same 20 bytes.
               if have.get(i) != u or have_anim.get(i, 0) != desired.layer_animations.get(i, 0)]
    if changed:
        # Without a board read to diff against (the preview), nothing is known to be new: say
        # so rather than labelling every layer "(new)", which read as if the board were empty.
        unknown = current is None
        what = ", ".join(f"{i}{'' if (unknown or i in have) else ' (new)'}" for i, _u, _a in changed)
        ops.append(WriteOp(R.WRITE_LAYER_LIST, R.encode_layer_list_entries(changed),
                           f"layer list: {what}" + (" (full write; the flash diffs first)" if unknown else "")))

    # On the board and no longer in the profile.
    removed = [i for i in sorted(have) if i not in desired.layer_uuids]
    if removed:
        ops.append(WriteOp(R.WRITE_LAYER_LIST, R.encode_layer_list_deletes(removed),
                           f"layer list: remove {', '.join(map(str, removed))}"))
        for idx in removed:
            ops.append(WriteOp(R.WRITE_LAYER_DATA, _blank_layer_payload(idx), f"wipe layer {idx}"))
            # As many LEDs as the board actually reports for that layer, NOT LED_COUNT: that
            # constant is 88 while a real read returns 136 per layer (its own comment flags the
            # discrepancy), and wiping 88 would leave a third of a deleted layer still lit.
            count = len(current.leds.get(idx, {})) if current else 0
            ops.append(WriteOp(R.WRITE_LED_MAP_DATA,
                               R.encode_led_map(idx, [
                                   R.encode_led_record(i, 0, keymap_read.UNSET_SATURATION)
                                   for i in range(count or LED_COUNT)]),
                               f"wipe led {idx}"))
    return ops


def compute_plan(desired: DesiredState, current: DesiredState | None = None, *,
                 full: bool | None = None, collect_orphans: bool = False,
                 device_slots: set[int] | None = None) -> list[WriteOp]:
    """Ordered write ops. full=True (or current=None) => rewrite everything; otherwise diff and
    emit only changed layers/leds (sparse per-record diffs are a Phase-C refinement).

    `collect_orphans` removes module slots the board carries that this profile does not
    reference. It is OFF by default and deliberately separate from `full`: deleting a config
    is the one destructive thing a flash can do, so it is something the user asks for, not
    something a routine flash decides.

    `device_slots` is which slots the board actually holds. It has to be passed in because
    `current` comes from a KEYMAP read, whose `modules` is empty -- so collecting orphans from
    `current.modules` alone found nothing, every time, which is why this never did anything
    even on a full flash.
    """
    full = full if full is not None else current is None
    ops: list[WriteOp] = []
    # --- garbage collection, only when asked and only when we know what is there -----------
    # NayaFlow's own removal sequence, captured 2026-09-03: point the bays away first, then
    # delete the list entry, then blank the slot. Doing it in that order means nothing ever
    # references a slot that is being emptied.
    orphans: list[int] = []
    have = set(device_slots) if device_slots is not None else set(current.modules) if current else set()
    if collect_orphans and current is not None and desired.module_list is not None:
        orphans = sorted(have - set(desired.module_list))
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

    # --- the layer IDENTITY table, before any layer data --------------------------------------
    # This is what a read matches app layers against. We never wrote it, so a board we had
    # flashed still advertised NayaFlow's layer UUIDs while carrying our records -- and importing
    # from that board attributed every binding to whichever profile owned those old UUIDs.
    #
    # Emitted only on a real difference. A flash that changes nothing about the layer set must
    # not rewrite identities, because a rewrite is the one operation here that could confuse a
    # board we have not tested this against.
    ops.extend(_layer_list_ops(desired, current))

    for idx in sorted(desired.layers):
        # A modelled key owns its second bank. Added to `desired` itself, not just to the
        # payload, so the read-back verify checks that each blanked slot really came back empty.
        desired.layers[idx].update(_own_second_bank(desired.layers[idx],
                                                    desired.keep_second_bank.get(idx, set())))
        if full or current is None or _layer_needs_write(desired.layers[idx],
                                                         current.layers.get(idx, {})):
            ops.append(WriteOp(R.WRITE_LAYER_DATA,
                               _full_layer_payload(idx, desired.layers[idx],
                                                   (current.layers.get(idx) if current else None)),
                               f"layer {idx}"))
    for idx in sorted(desired.leds):
        if desired.leds[idx] and (full or current is None or desired.leds[idx] != current.leds.get(idx)):
            ops.append(WriteOp(R.WRITE_LED_MAP_DATA,
                               _led_payload(idx, desired.leds[idx],
                                            (current.leds.get(idx) if current else None),
                                            desired.module_leds.get(idx)),
                               f"led {idx}"))
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
    # --- last: the full layer list, which is what puts the lighting back --------------------
    ops.extend(_lighting_restore_ops(desired, ops))
    # Applied to the FINISHED plan so every op is covered however it was built, and so the
    # preview the user confirms is the list of writes that will actually be sent.
    return [part for op in ops for part in split_for_two_frames(op)]


LIGHTING_RESTORE_LABEL = "layer list (restore lighting)"


def lighting_restore_payload(layer_uuids: dict[int, bytes], layer_animations: dict[int, int]) -> bytes:
    """The full layer table, byte-identical to what the board holds when the uuids and animations
    came from it. This is the one write that clears a runtime LED effect."""
    entries = [(i, u, layer_animations.get(i, 0)) for i, u in sorted(layer_uuids.items())]
    return R.encode_layer_list_entries(entries)


def _lighting_restore_ops(desired: DesiredState, ops: list[WriteOp]) -> list[WriteOp]:
    """End every flash with the FULL layer list.

    Measured 2026-09-10 (docs/plan-status.md item 4): a runtime LED effect -- engaged with an LED
    key or the 0xED select-effect command -- survives layer data, LED map and module writes, and
    NayaFlow's own flash never clears it because, exactly like _layer_list_ops, it writes the list
    only when a layer is added, removed or re-identified. Writing the list, even byte-identical,
    drops BOTH halves back to the stored animation and colours, from one frame sent to the left.
    So a flash ends with it, whether or not anything above changed: after "Flash", the board shows
    the profile, lighting included.

    Same guard as _layer_list_ops -- a complete identity table or nothing, never a partial one.
    Skipped when the ops above already carry this exact payload (a board flashed from scratch)."""
    if not desired.layer_uuids or set(desired.layer_uuids) != set(desired.layers):
        return []
    payload = lighting_restore_payload(desired.layer_uuids, desired.layer_animations)
    if any(op.sub == R.WRITE_LAYER_LIST and op.payload == payload for op in ops):
        return []
    return [WriteOp(R.WRITE_LAYER_LIST, payload, LIGHTING_RESTORE_LABEL)]


def _list_differs(desired: DesiredState, current: DesiredState | None) -> bool:
    """Whether the module list needs rewriting. Without a read we cannot tell, so we do."""
    if current is None or current.module_list is None:
        return True
    return desired.module_list != current.module_list


# Two CDC frames carry this many payload bytes: the first holds CHUNK_MAX, and every
# continuation re-sends the leading index byte, so it holds CHUNK_MAX - 1.
MAX_WRITE_PAYLOAD = R.CHUNK_MAX * 2 - 1


def _record_offsets(sub: int, body: bytes) -> list[int] | None:
    """Byte offsets in `body` where a record starts, plus its end. None if unsure.

    Returning None is the safe answer and the caller then leaves the payload alone: a
    split at the wrong offset would tear a record in half and write nonsense to a
    keyboard, which is far worse than the hang this is avoiding.
    """
    if sub == R.WRITE_LED_MAP_DATA:
        return list(range(0, len(body) + 1, 4)) if len(body) % 4 == 0 else None
    if sub == R.WRITE_LAYER_DATA:
        # The walker every read uses, so the boundaries cannot drift from the ones the
        # device itself produces.
        offsets, i = [0], 0
        for _idx, _typ, param in keymap_read.parse_records(body):
            i += 3 + len(param)
            offsets.append(i)
        return offsets if i == len(body) else None   # trailing bytes mean we misread it
    return None


def split_for_two_frames(op: WriteOp) -> list[WriteOp]:
    """One write, or several that each fit in two CDC frames.

    A third frame hangs firmware 3.28.7 until it is power-cycled (SCRUM-100). Writes apply
    by record index -- proved on hardware by sending records 120-135 as their own write and
    watching them land exactly there -- so several smaller writes are equivalent to one
    large one, and cost a board that could have taken the large one nothing.

    Payloads we cannot parse into records are returned untouched. That leaves the layer
    list and the module config as they are; both are far below the limit in practice, and
    guessing at their boundaries to save a frame is not a trade worth making.
    """
    if len(op.payload) <= MAX_WRITE_PAYLOAD:
        return [op]
    index, body = op.payload[:1], op.payload[1:]
    offsets = _record_offsets(op.sub, body)
    if not offsets:
        return [op]

    parts, start = [], 0
    for k in range(1, len(offsets)):
        # Every part re-sends the index byte, so the budget for records is one less.
        if offsets[k] - start > MAX_WRITE_PAYLOAD - 1:
            parts.append((start, offsets[k - 1]))
            start = offsets[k - 1]
    parts.append((start, offsets[-1]))
    parts = [(a, b) for a, b in parts if b > a]
    if len(parts) < 2:
        return [op]                      # one record is already too big; nothing to gain
    return [WriteOp(op.sub, index + body[a:b],
                    f"{op.label} (part {n} of {len(parts)})", cat=op.cat)
            for n, (a, b) in enumerate(parts, 1)]


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
          full: bool | None = None, dry_run: bool = True, reader=None,
          collect_orphans: bool = False, device_slots: set[int] | None = None) -> dict:
    """Compute + (optionally) send. dry_run=True (default) sends NOTHING — returns the plan,
    the rendered frames, and a summary. dry_run=False requires a connected transport and is the
    only path that touches the device (ack-checked per frame, then verified via `reader`, a
    callable returning a fresh device read as a DesiredState)."""
    plan = compute_plan(desired, current, full=full,
                        collect_orphans=collect_orphans, device_slots=device_slots)
    rendered = render_frames(plan, dest)
    summary = {
        "dest": f"0x{dest:02x}",
        "ops": [{"label": op.label, "sub": f"0x{op.sub:04x}", "payload_bytes": len(op.payload),
                 "frames": len(frames)} for op, (_, frames) in zip(plan, rendered)],
        "total_frames": sum(len(f) for _, f in rendered),
        "total_bytes": sum(len(op.payload) for op in plan),
    }
    if dry_run:
        return {"dry_run": True, "summary": summary, "dropped": list(desired.dropped),
                "frames": [f.hex() for _, frames in rendered for f in frames]}

    if transport is None:
        raise ValueError("dry_run=False requires a connected transport")
    out = _apply(plan, rendered, transport, desired, reader)
    # Carried through the write path too: a flash that verified is still not a flash that wrote
    # everything the user asked for, and the result is the only place that can say so.
    if desired.dropped:
        out["dropped"] = list(desired.dropped)
    return out


def diff_desired(a: "DesiredState", b: "DesiredState") -> list[dict]:
    """Records/leds in `a` (desired) that differ from `b` (device read-back). Empty = verified.
    Only the positions/leds `a` sets are checked — a full re-read has extra padding we ignore.

    A position ABSENT from the read-back counts as NONE, the same rule `_layer_needs_write`
    applies and for the same reason: on the wire, absent and empty are the same record. What
    made this matter (SCRUM-112): a layer with no second-bank records reads back as 82 records
    and stops at 0x51 -- the device does not return the bank at all -- while `compute_plan` adds
    the NONE shadows a profile owes for every key it sets. The write diff saw absent == NONE,
    correctly skipped the layer, and this function then demanded those NONEs from a read that
    never carries them. Two real flashes on 2026-09-21 wrote and verified perfectly on layer 0
    and were reported "verify-failed" on the two layers they had rightly left alone.
    """
    out = []
    empty = (R.NONE_BEH, b"")
    for idx, poss in a.layers.items():
        for pos, rec in poss.items():
            if b.layers.get(idx, {}).get(pos, empty) != rec:
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
                # 0xEA is the firmware saying no to the VALUE (measured 2026-09-11: a 10 s idle
                # timeout is acked with 0xEA and not stored). Anything else is a transport or
                # framing problem. Both stop the flash; the reason should say which.
                reason = ("rejected by the firmware (ack flag 0xEA): the value is outside what it "
                          "accepts, and nothing was stored" if flags == R.ACK_REJECTED
                          else "bad or missing ack — not continuing")
                return {"status": "aborted", "op": label, "frame": i, "ack_flags": flags,
                        "sent": sent, "reason": reason}
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
    # A bay names a profile of its own type or nothing. A row naming a profile of another
    # type (a read once stored a Track profile in a Tune bay, 2026-09-17) would have put a
    # Track slot in the Tune bay byte; the row is dropped instead, as if it had never been
    # stored, and the layer follows the base layer like any other bay it says nothing about.
    for order, bays in bays_by_layer.items():
        for location, value in list(bays.items()):
            if value in ("transparent", "disabled") or not value:
                continue
            want = location.split(":", 1)[0].upper()
            if types.get(value) != want:
                del bays[location]
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
            elif code:
                # A combined row of two KEY actions ("C_VOL_DOWN - C_VOL_UP" on pinch & spread)
                # is a binding per half, not the axis's motion. Skipping it wrote the default
                # motion instead, so any pair picked for an unsplit pinch flashed as zoom. The
                # read-back compare (rest._module_gestures) already expects these halves. A
                # motion pair keeps the path above, which owns selectors and invert. An
                # explicit split half still wins over the pair.
                minus, plus = module_fields.split_pair(code)
                if (minus and plus and module_fields.motion_record(minus) is None
                        and module_fields.motion_record(plus) is None):
                    spec["minus"] = spec["minus"] or minus
                    spec["plus"] = spec["plus"] or plus
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

    # Each entry carries the board's own type byte for its slot, so a slot under a uuid we
    # never stored (every slot NayaFlow wrote) can still template a new profile of its type.
    slot_type = ml.list_types(mod_read.get("list"))
    device_list = [{"slot": slot, "uuid": uuid, "type": slot_type.get(int(slot))}
                   for uuid, slot in (mod_read.get("by_uuid") or {}).items()]
    device_slots = {}
    for slot, fields in (mod_read.get("slots") or {}).items():
        device_slots[int(slot)] = {int(f["field"]): (f["type"], bytes.fromhex(f["value"]))
                                   for f in fields}

    base_order = min(order_of.values()) if order_of else 0
    layout = ml.plan(bays_by_layer, types, device_list, device_slots, base_order=base_order,
                     captured_from=captured_from)
    # Reported, not enforced here: the preview shows the gaps and the flash route refuses them
    # unless told otherwise, so a dry run can still describe a profile that is not ready.
    layout["baseBayGaps"] = ml.missing_base_bays(bays_by_layer.get(base_order, {}))

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
        # Each profile carries its own scroll direction convention (SCRUM-62).
        cfg = ml.overlay(layout["templates"][cid], types[cid], bindings.get(cid, {}),
                         axes.get(cid, {}), settings.get(cid, {}),
                         convention=module_fields.convention_of(settings.get(cid)))
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
